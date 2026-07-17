# AILibreTranslater — agent guide

## Entrypoint & run

- `python main.py` — starts FastAPI on `0.0.0.0:5555`
- `start.bat` — alias for `python main.py`
- Single route: `POST /translate` — expects `q` (text), `source` (default `"auto"`), `target` (required)
- Provider selection: `TRANSLATOR_PROVIDER` env var or `--provider <name>`

## Architecture

Flat single-module project (no `__init__.py`, no packages).

```
translator.py    — LLMTranslator + fallback chain logic
config.py        — PROVIDERS dict + TRANSLATION_CHAIN
main.py          — FastAPI app + uvicorn launcher
prompt_template.py — system/user prompt templates (hardcoded en→ru)
validator.py     — script-based language validation (Cyrillic ratio ≥ 0.5)
```

## Key quirks

- **source/target hardcoded**: `translator.py:126-127` always overrides to `"en"` / `"ru"`. HTTP `source`/`target` params are ignored for LLM steps. Non-LLM fallbacks (`google`, `libretranslate`) use the original request params.
- **System prompt** (`prompt_template.py:34`) is entirely in Russian, en→ru only.
- **Fallback chain**: `config.py:12-15` — ordered list of steps. Each step can be an LLM (with provider, prefill, temperature, multiplier overrides) or a non-LLM translator.
- **Dynamic max_tokens**: `input_chars / 4 * multiplier`, clamped to `[256, cap]`. Set per-step in `TRANSLATION_CHAIN` (`multiplier`, `cap`). Set `"max_tokens": null` to remove the limit entirely.
- **prefill logic**: If `"prefill"` key is present in step — use that value (can be `None` to disable). If absent — fall back to provider's `prefill` from `PROVIDERS`.
- **Output cleaning** (`_clean_output`, line 107): regex strips trailing English reasoning after `\n\n` + trigger words (Wait, Let, I need, Original:, etc.). The regex may need extension for new patterns.
- **No tests, no README, no CI**.

## Dependencies

`requirements.txt` — `fastapi`, `uvicorn`, `openai`, `pydantic`, `httpx`. `httpx` is only used by Google/LibreTranslate fallback functions; not required for pure-LLM chains.

## Logging

`main.py:8-14` — root logger at `DEBUG`, httpx/httpcore throttled to `WARNING`. Content is logged at INFO only when `LOG_TRANSLATION_CONTENT = True` in config.

## Validation

`validator.py:31` — checks `alphabetic_chars_in_target_script / total_alphabetic_chars >= 0.5`. Skips if target language has no script patterns defined. Cyrillic is the only script currently exercised.
