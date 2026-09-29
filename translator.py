import logging
import re
import time
from collections import Counter

import httpx
from openai import AsyncClient

import cache_manager
import config
import markdown_guard
import stats_manager
from prompt_template import LANGUAGE_NAMES, format_prompt
from validator import validate_translation

logger = logging.getLogger(__name__)

TRANSLATION_TIMEOUT = 30

# Version of the translation pipeline, stamped into every cache entry.
# Bump it whenever a change makes translations produced by the previous code
# suspect — a rewritten prompt, a different model, a new mask rule.  A bump
# alone never re-translates: cached entries are only redone when the static
# check in `_cached_defect` says they are wrong (see translate()).
#
#   1  versioning introduced; inline Markdown masking
#   2  block-level markers masked (headings, rules, quotes, hard breaks, link
#      brackets), a rule that ended the source is restored if the model drops
#      it, and the translation keeps the source's line endings
TRANSLATOR_VERSION = 2

URL_PATTERN = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")


def restore_urls(original: str, translation: str) -> str:
    orig_urls = URL_PATTERN.findall(original)
    if not orig_urls:
        return translation

    trans_urls = URL_PATTERN.findall(translation)
    if not trans_urls:
        return translation

    pairs = []
    for i, (orig_url, trans_url) in enumerate(zip(orig_urls, trans_urls)):
        if orig_url != trans_url:
            pairs.append((i, trans_url, orig_url))

    if not pairs:
        return translation

    result = translation
    for i, trans_url, _ in sorted(pairs, key=lambda p: len(p[1]), reverse=True):
        placeholder = f"\x00URL_{i}\x00"
        result = result.replace(trans_url, placeholder, 1)

    for i, _, orig_url in pairs:
        placeholder = f"\x00URL_{i}\x00"
        result = result.replace(placeholder, orig_url, 1)

    logger.debug("Restored URLs in translation: %d pairs fixed", len(pairs))
    return result


class TranslationError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code


def source_line_ending(text: str) -> str | None:
    """Dominant line ending of the source: '\\r\\n', '\\n', or None.

    None means the text has no line breaks at all, or is genuinely mixed — in
    both cases there is no single shape to impose.
    """
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    total = crlf + lf
    if total == 0:
        return None
    if crlf * 2 > total:
        return "\r\n"
    if lf * 2 > total:
        return "\n"
    return None


def _leading_whitespace(text: str) -> str:
    return text[: len(text) - len(text.lstrip())]


def _trailing_whitespace(text: str) -> str:
    return text[len(text.rstrip()) :]


def restore_surrounding_whitespace(original: str, translation: str) -> str:
    """Give the translation the source's leading and trailing whitespace.

    SillyTavern's built-in translate extension splits a message at every
    markdown image, translates each piece on its own and re-inserts the links
    itself, with no separator of its own
    (``public/scripts/extensions/translate/index.js``).  The piece it sends
    therefore ends with the blank line that separated the text from the image,
    and our reply is glued straight onto that link.  A stripped reply turns
    ``...\\n\\n---\\n\\n`` + ``![img](url)`` into ``---![img](url)``, which is
    neither a rule nor an image: markdown prints it as text and both disappear.

    The cache key is computed from the stripped text, so preserving this costs
    nothing — existing entries still hit.
    """
    return (
        _leading_whitespace(original)
        + translation.strip()
        + _trailing_whitespace(original)
    )


def restore_line_endings(original: str, translation: str) -> str:
    """Give the translation the line endings its source used.

    A model normalises CRLF to LF on its own, but the line ending is part of
    the shape the client was given, not something translation may change: it
    decides how the message is rendered.  SillyTavern renders CRLF and LF
    differently, so a `---` that stayed a rule in the source stops being one
    after normalisation.  The source is the authority, exactly as it is for
    URLs in restore_urls.

    Applied on the way out and on the way back from the cache, because the
    cache key normalises line endings — one entry therefore serves both a CRLF
    and an LF request, and each of them must get its own.
    """
    wanted = source_line_ending(original)
    if wanted == "\r\n":
        return re.sub(r"(?<!\r)\n", "\r\n", translation)
    if wanted == "\n":
        return translation.replace("\r\n", "\n")
    return translation


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_max_output_tokens(
    text: str, multiplier: float = 5.0, cap: int = 16384
) -> int:
    input_tokens = estimate_tokens(text)
    return max(256, min(cap, int(input_tokens * multiplier)))


async def _translate_google(text: str, source: str, target: str) -> str:
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": source if source != "auto" else "auto",
        "tl": target,
        "dt": "t",
        "q": text,
    }
    async with httpx.AsyncClient(timeout=TRANSLATION_TIMEOUT) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if not data or not data[0]:
            raise TranslationError("Google returned empty response")
        return "".join(part[0] for part in data[0])


async def _translate_libretranslate(text: str, source: str, target: str) -> str:
    payload = {
        "q": text,
        "source": source if source != "auto" else "auto",
        "target": target,
        "format": "text",
    }
    headers = {}
    if config.LIBRETRANSLATE_API_KEY:
        headers["Authorization"] = f"Bearer {config.LIBRETRANSLATE_API_KEY}"

    async with httpx.AsyncClient(timeout=TRANSLATION_TIMEOUT) as client:
        resp = await client.post(
            config.LIBRETRANSLATE_URL, json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise TranslationError(f"LibreTranslate error: {data['error']}")
        if "translatedText" not in data:
            raise TranslationError(
                f"LibreTranslate unexpected response: {str(data)[:200]}"
            )
        return data["translatedText"]


_NON_LLM_TRANSLATORS = {
    "google": _translate_google,
    "libretranslate": _translate_libretranslate,
}


def _mask_if_needed(text: str) -> markdown_guard.MaskedText | None:
    """Mask Markdown constructs, unless preservation is disabled or none found."""
    if not config.PRESERVE_MARKDOWN or not markdown_guard.has_markdown(text):
        return None
    return markdown_guard.mask_markdown(
        text, translate_fenced=config.TRANSLATE_FENCED_CODE
    )


def _finish(source: str, translated: str) -> str:
    """Put the source's own shape back on a translation before returning it.

    Applied to fresh output and to a cache hit alike, because a stored
    translation is stripped: the leading and trailing whitespace and the line
    endings all belong to the request that came in, not to what the model or
    the cache file happen to hold.
    """
    return restore_line_endings(
        source, restore_surrounding_whitespace(source, restore_urls(source, translated))
    )


def _validation_text(content: str) -> str:
    """Text used for target-language validation.

    Code inside fenced blocks is not expected to be in the target script
    (identifiers, strings, or verbatim-preserved blocks), so it is stripped
    before checking that the surrounding prose was translated.
    """
    if not config.PRESERVE_MARKDOWN:
        return content
    return markdown_guard.without_fenced_blocks(content)


def _log_missing_markers(masked: markdown_guard.MaskedText, missing: list[int]):
    """Report dropped placeholders, split by how much damage they do.

    A lost structural marker (heading, rule, quote, link bracket) means the
    translation lost document structure; a lost inline marker (emphasis, code,
    tag, URL) is only a formatting blemish.
    """
    if not missing:
        return
    structure = [i for i in missing if masked.is_structural(i)]
    inline = [i for i in missing if not masked.is_structural(i)]
    if structure:
        logger.warning(
            "Markdown structure markers lost by the model: %s "
            "(headings, rules, quotes, link/image brackets)",
            structure,
        )
    if inline:
        logger.warning(
            "Markdown inline markers lost by the model: %s "
            "(emphasis, code, tags, urls)",
            inline,
        )


def cached_defect(source: str, cached: str, target: str) -> str | None:
    """Static check of a cached translation.  Returns why it is unusable, or None.

    Deterministic, no model and no network involved, so it can be re-run on
    every cache hit:

    1. the translation must carry every Markdown marker the source has.  Both
       texts are masked with the same rules and the two marker inventories are
       compared, so a translation that lost ``*``, ``**``, ``---`` or ``##`` on
       the way out is rejected — comparing against the source rather than
       guessing what the model would keep.  Markers the translation *gained*
       are ignored: the check is one-directional;
    2. the translation must be in the target script.

    A stored translation has already been restored, so its markers are back in
    place; that is exactly why the comparison is mask-vs-mask and not a search
    for placeholders.
    """
    if config.PRESERVE_MARKDOWN:
        translate_fenced = config.TRANSLATE_FENCED_CODE
        wanted = markdown_guard.mask_markdown(
            source, translate_fenced=translate_fenced
        ).tokens
        if wanted:
            have = markdown_guard.mask_markdown(
                cached, translate_fenced=translate_fenced
            ).tokens
            missing = Counter(wanted) - Counter(have)
            if missing:
                lost = ", ".join(
                    f"{token!r}x{count}" for token, count in sorted(missing.items())
                )
                return f"lost Markdown marker(s): {lost}"
    if not validate_translation(_validation_text(cached), target):
        return f"not in target language ({target})"
    return None


class LLMTranslator:
    def __init__(self, provider_name: str | None = None):
        if provider_name:
            if provider_name not in config.PROVIDERS:
                raise ValueError(
                    f"Unknown provider '{provider_name}'. "
                    f"Available: {list(config.PROVIDERS.keys())}"
                )
            config.DEFAULT_PROVIDER = provider_name
        self.default_provider = config.DEFAULT_PROVIDER
        self.chain = config.TRANSLATION_CHAIN or self._default_chain()
        self._llm_clients: dict[str, AsyncClient] = {}
        self._validate_chain()
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.translations: int = 0
        self.cached: int = 0
        self.stale: int = 0
        self.errors: int = 0
        # Cache keys already re-translated in this process, so a translation
        # that fails the static check on every attempt is not paid for twice.
        self._refreshed: set[str] = set()
        self.reasoning_effort: dict[str, str | None] = {
            p: config.get_reasoning_effort(p) for p in config.PROVIDERS
        }

    async def aclose(self):
        # openai 2.x names the coroutine `close`; 1.x had `aclose`. Accept both,
        # otherwise the client is never closed and every shutdown logs a warning.
        for name, client in self._llm_clients.items():
            closer = getattr(client, "close", None) or getattr(client, "aclose")
            try:
                await closer()
                logger.debug("Closed client for provider %s", name)
            except Exception as e:
                logger.warning("Failed to close client for provider %s: %s", name, e)
        self._llm_clients.clear()

    def _default_chain(self) -> list[dict]:
        return [
            {"type": "llm", "provider": config.DEFAULT_PROVIDER},
            {"type": "google"},
            {"type": "libretranslate"},
        ]

    def _validate_chain(self):
        for i, step in enumerate(self.chain):
            step_type = step.get("type", "llm")
            if step_type == "llm":
                provider = step.get("provider")
                if not provider:
                    raise ValueError(f"Step {i}: LLM step missing 'provider'")
                if provider not in config.PROVIDERS:
                    raise ValueError(
                        f"Step {i}: unknown provider '{provider}'. "
                        f"Available: {list(config.PROVIDERS.keys())}"
                    )

    def _get_client(self, provider_name: str) -> AsyncClient:
        if provider_name not in self._llm_clients:
            cfg = config.PROVIDERS[provider_name]
            self._llm_clients[provider_name] = AsyncClient(
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
            )
        return self._llm_clients[provider_name]

    def _step_label(self, step: dict) -> str:
        t = step.get("type", "llm")
        if t == "llm":
            p = step["provider"]
            m = config.PROVIDERS[p]["model"]
            return f"LLM {p}/{m}"
        return t.capitalize()

    def set_reasoning_effort(self, provider: str, effort: str | None) -> None:
        if provider not in self.reasoning_effort:
            raise ValueError(f"Unknown provider '{provider}'")
        self.reasoning_effort[provider] = effort
        config.set_reasoning_effort(provider, effort)
        logger.debug("Reasoning effort for %s set to %s", provider, effort)

    def toggle_reasoning(self, provider: str, direction: str = "next") -> str | None:
        effort = self.reasoning_effort.get(provider)
        levels = list(config.REASONING_EFFORT_LEVELS)
        if direction == "prev":
            seq = [None] + levels
            idx = seq.index(effort) - 1 if effort in seq else len(seq) - 1
            new_effort = seq[idx % len(seq)]
        else:
            seq = levels + [None]
            idx = seq.index(effort) + 1 if effort in seq else 0
            new_effort = seq[idx % len(seq)]
        self.set_reasoning_effort(provider, new_effort)
        return new_effort

    async def translate(self, text: str, source: str, target: str) -> dict:
        source_lang = source
        target_lang = target

        req_start = time.monotonic()
        tokens_before = (self.prompt_tokens, self.completion_tokens)
        key = cache_manager.cache_key(source_lang, target_lang, text)

        entry = cache_manager.get_entry(source_lang, target_lang, text)
        cached: str = ""
        if entry is not None:
            stored_text = entry.get("translated_text")
            if isinstance(stored_text, str):
                cached = stored_text
            else:
                # a truncated or hand-edited entry: treat it as no entry at all
                logger.warning(
                    "Cache entry %s has no usable translated_text, ignoring it",
                    key[:12],
                )
                entry = None
        if entry is not None:
            defect = cached_defect(text, cached, target_lang)
            stored = cache_manager.get_version(entry)

            if defect is None:
                # Still good.  Adopt the current version if the entry predates
                # it — no re-translation, just a fresh stamp.
                self.cached += 1
                if cache_manager.set_version(key, TRANSLATOR_VERSION):
                    logger.info(
                        "Cached translation %s (was v%d) adopted v%d",
                        key[:12],
                        stored,
                        TRANSLATOR_VERSION,
                    )
                logger.info("Using cached translation")
                stats_manager.log_event(
                    "cache_hit",
                    hash_key=key,
                    source=source_lang,
                    target=target_lang,
                    version=TRANSLATOR_VERSION,
                    latency_s=time.monotonic() - req_start,
                    input_chars=len(text),
                    preview=text[:80],
                )
                return {"translatedText": _finish(text, cached)}

            if key in self._refreshed:
                # Already re-translated once this run and the new one failed the
                # same check — serve the cache instead of paying again.
                self.cached += 1
                logger.warning(
                    "Cached translation %s still defective (%s) after a "
                    "refresh — serving it",
                    key[:12],
                    defect,
                )
                stats_manager.log_event(
                    "cache_defect",
                    hash_key=key,
                    source=source_lang,
                    target=target_lang,
                    version=stored,
                    latency_s=time.monotonic() - req_start,
                    input_chars=len(text),
                    preview=text[:80],
                    error=defect,
                )
                return {"translatedText": _finish(text, cached)}

            self._refreshed.add(key)
            self.stale += 1
            logger.info(
                "Cached translation %s rejected — %s (made by v%d, running v%d)",
                key[:12],
                defect,
                stored,
                TRANSLATOR_VERSION,
            )
            stats_manager.log_event(
                "cache_stale",
                hash_key=key,
                source=source_lang,
                target=target_lang,
                version=stored,
                latency_s=time.monotonic() - req_start,
                input_chars=len(text),
                preview=text[:80],
                error=defect,
            )
            cache_manager.invalidate_cache(key)

        if not self.chain:
            raise TranslationError("TRANSLATION_CHAIN is empty", 500)

        total = len(self.chain)
        errors: list[str] = []
        failed_labels: list[str] = []

        for idx, step in enumerate(self.chain):
            step_num = idx + 1
            step_type = step.get("type", "llm")
            label = self._step_label(step)
            start = time.monotonic()

            try:
                if step_type == "llm":
                    result = await self._translate_via_llm(
                        text, source_lang, target_lang, step, step["provider"]
                    )
                elif step_type in _NON_LLM_TRANSLATORS:
                    masked = _mask_if_needed(text)
                    result = await _NON_LLM_TRANSLATORS[step_type](
                        masked.text if masked else text, source_lang, target_lang
                    )
                    if masked and result:
                        result = markdown_guard.restore_markdown(result, masked)
                else:
                    logger.warning(
                        "[%d/%d] %s — unknown step type, skipped",
                        step_num,
                        total,
                        label,
                    )
                    errors.append(f"step {step_num}: unknown type '{step_type}'")
                    failed_labels.append(label)
                    continue

                elapsed = time.monotonic() - start

                if result and result.strip():
                    clean = result.strip()
                    wanted_eol = source_line_ending(text)
                    if wanted_eol == "\r\n" and source_line_ending(clean) == "\n":
                        logger.debug(
                            "Model normalised CRLF to LF; restoring the source's "
                            "line endings"
                        )
                    clean = _finish(text, clean)
                    if wanted_eol and source_line_ending(clean) != wanted_eol:
                        logger.warning(
                            "Line endings still differ from the source: %r -> %r",
                            wanted_eol,
                            source_line_ending(clean),
                        )
                    self.translations += 1
                    logger.info(
                        "[%d/%d] %s — SUCCESS (%.1fs)", step_num, total, label, elapsed
                    )
                    if config.LOG_TRANSLATION_CONTENT:
                        logger.info("Content: %s", clean)
                    cache_manager.set_cache(
                        source_lang, target_lang, text, clean, TRANSLATOR_VERSION
                    )
                    stats_manager.log_event(
                        "success",
                        hash_key=key,
                        source=source_lang,
                        target=target_lang,
                        step=label,
                        steps_failed=failed_labels or None,
                        version=TRANSLATOR_VERSION,
                        latency_s=time.monotonic() - req_start,
                        input_chars=len(text),
                        output_chars=len(clean),
                        prompt_tokens=self.prompt_tokens - tokens_before[0],
                        completion_tokens=self.completion_tokens - tokens_before[1],
                        preview=text[:80],
                    )
                    return {"translatedText": clean}

                logger.warning(
                    "[%d/%d] %s — empty result (%.1fs)", step_num, total, label, elapsed
                )
                errors.append(f"step {step_num}: empty result")
                failed_labels.append(label)

            except TranslationError as e:
                elapsed = time.monotonic() - start
                logger.warning(
                    "[%d/%d] %s — FAILED: %s (%.1fs)",
                    step_num,
                    total,
                    label,
                    e.message,
                    elapsed,
                )
                errors.append(f"step {step_num}: {e.message}")
                failed_labels.append(label)
            except Exception as e:
                elapsed = time.monotonic() - start
                logger.warning(
                    "[%d/%d] %s — FAILED: %s (%.1fs)",
                    step_num,
                    total,
                    label,
                    e,
                    elapsed,
                )
                errors.append(f"step {step_num}: {e}")
                failed_labels.append(label)

        self.errors += 1
        stats_manager.log_event(
            "error",
            source=source_lang,
            target=target_lang,
            steps_failed=failed_labels or None,
            latency_s=time.monotonic() - req_start,
            input_chars=len(text),
            error=f"All {total} translation steps failed",
        )
        raise TranslationError(
            f"All {total} translation steps failed. Errors: {'; '.join(errors)}",
            502,
        )

    async def _translate_via_llm(
        self,
        text: str,
        source: str,
        target: str,
        step: dict,
        provider_name: str,
    ) -> str:
        cfg = config.PROVIDERS[provider_name]
        client = self._get_client(provider_name)
        model = cfg["model"]

        if step.get("mode") == "completions":
            return await self._translate_via_completions(
                text,
                source,
                target,
                step,
                provider_name,
                client,
                model,
            )

        masked = _mask_if_needed(text)
        parts = format_prompt(source, target, masked.text if masked else text)
        user_content = parts["user"]
        if masked:
            user_content += markdown_guard.markdown_instruction(
                masked, translate_fenced=config.TRANSLATE_FENCED_CODE
            )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": parts["system"]},
            {"role": "user", "content": user_content},
        ]

        if "prefill" in step:
            prefill_text = step["prefill"]
        else:
            prefill_text = cfg.get("prefill")

        if prefill_text:
            messages.append({"role": "assistant", "content": prefill_text})

        temperature = step.get("temperature", 0.0)

        api_type = cfg.get("api_type", "openai")

        if "reasoning_effort" in step:
            reasoning_effort = step["reasoning_effort"]
        else:
            reasoning_effort = self.reasoning_effort.get(provider_name)

        extra_body = {}
        if api_type == "deepseek":
            if reasoning_effort is None:
                extra_body["thinking"] = {"type": "disabled"}
            else:
                extra_body["thinking"] = {
                    "type": "enabled",
                    "reasoning_effort": reasoning_effort,
                }
        else:
            if reasoning_effort is not None:
                extra_body["reasoning_effort"] = reasoning_effort

        step_multiplier = step.get("multiplier", 5.0)
        step_cap = step.get("cap", 16384)
        if "max_tokens" in step:
            max_tokens = step["max_tokens"]
        else:
            max_tokens = estimate_max_output_tokens(text, step_multiplier, step_cap)

        logger.debug("Input text (%d chars): %r", len(text), text[:1000])
        logger.debug(
            "Messages sent:\n%s",
            "\n".join(f"  [{m['role']}] {m['content'][:200]}" for m in messages),
        )
        logger.debug(
            "LLM request: provider=%s model=%s api_type=%s max_tokens=%s temp=%.1f prefill=%s reasoning=%s input_chars=%d",
            provider_name,
            model,
            api_type,
            str(max_tokens),
            temperature,
            "yes" if prefill_text else "no",
            (extra_body.get("thinking") or {}).get("reasoning_effort")
            or extra_body.get("reasoning_effort")
            or (
                "off"
                if (extra_body.get("thinking") or {}).get("type") == "disabled"
                else "None"
            ),
            len(text),
        )

        if max_tokens is not None:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=extra_body or None,
            )
        else:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore
                temperature=temperature,
                extra_body=extra_body or None,
            )

        content = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason
        usage = response.usage
        if usage:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
            logger.debug("Token usage: %s", usage)
        logger.debug(
            "Raw response: finish_reason=%s content=%r", finish_reason, content
        )

        if content is None:
            logger.warning("LLM returned empty (finish_reason=%s)", finish_reason)
            raise TranslationError(
                f"LLM returned empty response (finish_reason={finish_reason})",
            )

        if prefill_text and content.startswith(prefill_text):
            content = content[len(prefill_text) :]

        content = content.strip()
        if "\n\nПеревод:" in content:
            content = content.split("\n\nПеревод:", 1)[-1].strip()

        if masked:
            missing = markdown_guard.missing_placeholders(content, masked)
            content = markdown_guard.restore_markdown(content, masked)
            _log_missing_markers(masked, missing)

        if not validate_translation(_validation_text(content), target):
            logger.warning(
                "Validation raw content (after strip): %r",
                content[:2000],
            )
            raise TranslationError(
                f"Output validation failed — not in target language ({target})",
            )

        return content

    async def _translate_via_completions(
        self,
        text: str,
        source: str,
        target: str,
        step: dict,
        provider_name: str,
        client,
        model: str,
    ) -> str:
        source_name = LANGUAGE_NAMES.get(source, source)
        target_name = LANGUAGE_NAMES.get(target, target)

        masked = _mask_if_needed(text)
        instruction = (
            markdown_guard.markdown_instruction(
                masked, translate_fenced=config.TRANSLATE_FENCED_CODE
            )
            if masked
            else ""
        )
        prompt = (
            f"<|channel|>user\n"
            f"Переведи следующий текст с {source_name} на {target_name}:\n\n"
            f"{masked.text if masked else text}{instruction}\n\n"
            f"Перевод:<|channel|>\n"
            f"<|channel|>assistant\n"
        )

        temperature = step.get("temperature", 0.0)
        step_multiplier = step.get("multiplier", 5.0)
        step_cap = step.get("cap", 16384)
        if "max_tokens" in step:
            max_tokens = step["max_tokens"]
        else:
            max_tokens = estimate_max_output_tokens(text, step_multiplier, step_cap)

        logger.debug("Completions prompt (%d chars): %r", len(prompt), prompt[:300])
        logger.debug(
            "LLM request: provider=%s model=%s max_tokens=%s temp=%.1f input_chars=%d",
            provider_name,
            model,
            str(max_tokens),
            temperature,
            len(text),
        )

        if max_tokens is not None:
            response = await client.completions.create(
                model=model,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            response = await client.completions.create(
                model=model,
                prompt=prompt,
                temperature=temperature,
            )

        content = response.choices[0].text
        finish_reason = response.choices[0].finish_reason
        usage = response.usage
        if usage:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
            logger.debug("Token usage: %s", usage)
        logger.debug(
            "Raw completions: finish_reason=%s content=%r", finish_reason, content
        )

        if not content or not content.strip():
            raise TranslationError(
                f"LLM returned empty response (finish_reason={finish_reason})",
            )

        if "<|channel|>" in content:
            content = content.split("<|channel|>")[-1]
        elif "<|channel>" in content:
            content = content.split("<|channel>")[-1]
        if "<|channel|>" in content:
            content = content.split("<|channel|>")[0]
        elif "<|channel>" in content:
            content = content.split("<|channel>")[0]

        content = content.strip()
        if "\n\nПеревод:" in content:
            content = content.split("\n\nПеревод:", 1)[-1].strip()

        if masked:
            missing = markdown_guard.missing_placeholders(content, masked)
            content = markdown_guard.restore_markdown(content, masked)
            _log_missing_markers(masked, missing)

        if not validate_translation(_validation_text(content), target):
            logger.warning(
                "Validation raw content (after strip): %r",
                content[:2000],
            )
            raise TranslationError(
                f"Output validation failed — not in target language ({target})",
            )

        return content
