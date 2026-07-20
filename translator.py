import logging
import re
import time

import httpx
from openai import AsyncClient

import cache_manager
import config
from prompt_template import LANGUAGE_NAMES, format_prompt
from validator import validate_translation

logger = logging.getLogger(__name__)

TRANSLATION_TIMEOUT = 30

URL_PATTERN = re.compile(r'https?://[^\s<>"\'\]\[\)\(]+')


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
    for i, trans_url, _ in reversed(pairs):
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


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_max_output_tokens(text: str, multiplier: float = 5.0, cap: int = 16384) -> int:
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
        resp = await client.post(config.LIBRETRANSLATE_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise TranslationError(f"LibreTranslate error: {data['error']}")
        if "translatedText" not in data:
            raise TranslationError(f"LibreTranslate unexpected response: {str(data)[:200]}")
        return data["translatedText"]


_NON_LLM_TRANSLATORS = {
    "google": _translate_google,
    "libretranslate": _translate_libretranslate,
}


class LLMTranslator:
    def __init__(self, provider_name: str | None = None):
        self.chain = getattr(config, "TRANSLATION_CHAIN", self._default_chain())
        self._llm_clients: dict[str, AsyncClient] = {}
        self._validate_chain()

    async def aclose(self):
        for name, client in self._llm_clients.items():
            try:
                await client.aclose()
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

    async def translate(self, text: str, source: str, target: str) -> dict:
        source_lang = source if source != "auto" else source
        target_lang = target

        cached = cache_manager.get_cache(source_lang, target_lang, text)
        if cached is not None:
            logger.info("Using cached translation")
            cached = restore_urls(text, cached)
            return {"translatedText": cached}

        if not self.chain:
            raise TranslationError("TRANSLATION_CHAIN is empty", 500)

        total = len(self.chain)
        errors: list[str] = []

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
                    result = await _NON_LLM_TRANSLATORS[step_type](
                        text, source_lang, target_lang
                    )
                else:
                    logger.warning("[%d/%d] %s — unknown step type, skipped", step_num, total, label)
                    errors.append(f"step {step_num}: unknown type '{step_type}'")
                    continue

                elapsed = time.monotonic() - start

                if result and result.strip():
                    clean = result.strip()
                    clean = restore_urls(text, clean)
                    logger.info("[%d/%d] %s — SUCCESS (%.1fs)", step_num, total, label, elapsed)
                    if config.LOG_TRANSLATION_CONTENT:
                        logger.info("Content: %s", clean)
                    cache_manager.set_cache(source_lang, target_lang, text, clean)
                    return {"translatedText": clean}

                logger.warning("[%d/%d] %s — empty result (%.1fs)", step_num, total, label, elapsed)
                errors.append(f"step {step_num}: empty result")

            except TranslationError as e:
                elapsed = time.monotonic() - start
                logger.warning("[%d/%d] %s — FAILED: %s (%.1fs)", step_num, total, label, e.message, elapsed)
                errors.append(f"step {step_num}: {e.message}")
            except Exception as e:
                elapsed = time.monotonic() - start
                logger.warning("[%d/%d] %s — FAILED: %s (%.1fs)", step_num, total, label, e, elapsed)
                errors.append(f"step {step_num}: {e}")

        raise TranslationError(
            f"All {total} translation steps failed. Errors: {'; '.join(errors)}", 502,
        )

    async def _translate_via_llm(
        self, text: str, source: str, target: str, step: dict, provider_name: str,
    ) -> str:
        cfg = config.PROVIDERS[provider_name]
        client = self._get_client(provider_name)
        model = cfg["model"]

        if step.get("mode") == "completions":
            return await self._translate_via_completions(
                text, source, target, step, provider_name, client, model, cfg,
            )

        parts = format_prompt(source, target, text)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": parts["system"]},
            {"role": "user", "content": parts["user"]},
        ]

        if "prefill" in step:
            prefill_text = step["prefill"]
        else:
            prefill_text = cfg.get("prefill")

        if prefill_text:
            messages.append({"role": "assistant", "content": prefill_text})

        temperature = step.get("temperature", 0.0)

        extra_body = {}
        reasoning_effort = step.get("reasoning_effort") or cfg.get("reasoning_effort")
        if reasoning_effort:
            extra_body["reasoning_effort"] = reasoning_effort

        step_multiplier = step.get("multiplier", 5.0)
        step_cap = step.get("cap", 16384)
        if "max_tokens" in step:
            max_tokens = step["max_tokens"]
        else:
            max_tokens = estimate_max_output_tokens(text, step_multiplier, step_cap)

        logger.debug("Input text (%d chars): %r", len(text), text[:1000])
        logger.debug("Messages sent:\n%s",
            "\n".join(f"  [{m['role']}] {m['content'][:200]}" for m in messages))
        logger.debug(
            "LLM request: provider=%s model=%s max_tokens=%s temp=%.1f prefill=%s input_chars=%d",
            provider_name, model, str(max_tokens), temperature,
            "yes" if prefill_text else "no", len(text),
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
        logger.debug("Raw response: finish_reason=%s content=%r", finish_reason, content)
        if usage:
            logger.debug("Token usage: %s", usage)

        if content is None:
            logger.warning("LLM returned empty (finish_reason=%s)", finish_reason)
            raise TranslationError(
                f"LLM returned empty response (finish_reason={finish_reason})",
            )

        if prefill_text and content.startswith(prefill_text):
            content = content[len(prefill_text):]

        content = content.strip()
        if "\n\nПеревод:" in content:
            content = content.split("\n\nПеревод:", 1)[-1].strip()

        if not validate_translation(content, target):
            logger.warning(
                "Validation raw content (after strip): %r", content[:2000],
            )
            raise TranslationError(
                f"Output validation failed — not in target language ({target})",
            )

        return content

    async def _translate_via_completions(
        self, text: str, source: str, target: str, step: dict, provider_name: str,
        client, model: str, cfg: dict,
    ) -> str:
        source_name = LANGUAGE_NAMES.get(source, source)
        target_name = LANGUAGE_NAMES.get(target, target)

        prompt = (
            f"<|channel|>user\n"
            f"Переведи следующий текст с {source_name} на {target_name}:\n\n{text}\n\n"
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
            provider_name, model, str(max_tokens), temperature, len(text),
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
        logger.debug("Raw completions: finish_reason=%s content=%r", finish_reason, content)
        if usage:
            logger.debug("Token usage: %s", usage)

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

        if not validate_translation(content, target):
            logger.warning(
                "Validation raw content (after strip): %r", content[:2000],
            )
            raise TranslationError(
                f"Output validation failed — not in target language ({target})",
            )

        return content
