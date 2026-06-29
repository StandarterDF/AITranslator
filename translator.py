import logging

from openai import AsyncClient, APIError

import config
from prompt_template import format_prompt, LANGUAGE_NAMES
from validator import validate_translation

logger = logging.getLogger(__name__)


class TranslationError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code


class LLMTranslator:
    def __init__(self, provider_name: str | None = None):
        if provider_name is None:
            provider_name = config.DEFAULT_PROVIDER
        if provider_name not in config.PROVIDERS:
            available = list(config.PROVIDERS.keys())
            raise ValueError(
                f"Unknown provider: {provider_name}. "
                f"Available: {available}"
            )

        self.provider_cfg = config.PROVIDERS[provider_name]
        self.client = AsyncClient(
            api_key=self.provider_cfg["api_key"],
            base_url=self.provider_cfg["base_url"],
        )
        self.model = self.provider_cfg["model"]

    async def translate(self, text: str, source: str, target: str) -> dict:
        parts = format_prompt(source, target, text)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": parts["system"]},
            {"role": "user", "content": parts["user"]},
        ]

        prefill_template = self.provider_cfg.get("prefill")
        prefill = None
        if prefill_template:
            source_name = LANGUAGE_NAMES.get(source, source) if source != "auto" else "auto-detected language"
            target_name = LANGUAGE_NAMES.get(target, target)
            prefill = (prefill_template
                .replace("{source}", source_name)
                .replace("{target}", target_name))
            messages.append({"role": "assistant", "content": prefill})

        extra_body = {}
        reasoning_effort = self.provider_cfg.get("reasoning_effort")
        if reasoning_effort:
            extra_body["reasoning_effort"] = reasoning_effort

        logger.info("Sending request to %s (max_tokens=8192)", self.model)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore
                temperature=0.0,
                max_tokens=8192,
                extra_body=extra_body or None,
            )
        except APIError as e:
            raise TranslationError(f"LLM API error: {e.message}", 502)
        except Exception as e:
            raise TranslationError(f"Translation failed: {str(e)}", 502)

        content = response.choices[0].message.content
        if content is None:
            raise TranslationError("LLM returned empty response", 502)

        if prefill and content.startswith(prefill):
            content = content[len(prefill):]

        content = content.strip()

        logger.info("Raw model output: %r", content[:500])
        logger.info("Cyrillic ratio: %.2f", sum(1 for c in content if '\u0400' <= c <= '\u04FF' or '\u0500' <= c <= '\u052F') / max(len(content), 1))

        if not validate_translation(content, target):
            logger.warning(
                "Validation failed for %s->%s: output doesn't look like target language",
                source, target,
            )
            raise TranslationError(
                f"Translation output validation failed — result is not in target language ({target})",
                502,
            )

        logger.info("Response: %s", content)
        return {"translatedText": content}
