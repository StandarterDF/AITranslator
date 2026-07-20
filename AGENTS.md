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
- **Step 1 — chat mode (DO NOT TOUCH)**: `"mode": "chat"` (default). Uses `client.chat.completions.create()` with system+user+assistant prefill. The provider's default prefill (`<|channel|>thought...`) works. This step is stable and must not be modified.
- **Step 2 — completions mode**: `"mode": "completions"`. Uses `client.completions.create(prompt=...)` — raw prompt with `<|channel|>` tokens, no prefill, no messages. The model outputs `<|channel|>thought\n...<|channel|>\n...translation...`. Parsing strips the thought block via `split("<|channel|>")[-1]`.
- **Step 2 NEVER uses prefill** — it's a raw completions request. The model reasons naturally in a thought block, then outputs the answer.
- **Output cleaning** (`_clean_output`, line 108): regex strips trailing English reasoning after `\n\n` + trigger words (Wait, Let, I need, Original:, etc.). Additionally, if `\n\nПеревод:` is found in the output, everything before it is discarded (English paraphrase from the model).
## Cache

- **DO NOT clear entire cache**. Only delete specific corrupt entries.
- Cache entries are JSON files in `cache/` directory, named by hash key.
- To delete a single entry: `python -c "import cache_manager; cache_manager.delete_cache('HASH_KEY')"` (full hash from log or file name).
- Log shows hash on cache hits: `Cached translation HASH_KEY`.
- The FastAPI app exposes `DELETE /cache/{hash_key}` and `DELETE /cache` routes — use the former, never the latter.
- `GET /cache` lists all entries with previews to find the right hash.

## Dependencies

`requirements.txt` — `fastapi`, `uvicorn`, `openai`, `pydantic`, `httpx`. `httpx` is only used by Google/LibreTranslate fallback functions; not required for pure-LLM chains.

## Logging

`main.py:8-14` — root logger at `DEBUG`, httpx/httpcore throttled to `WARNING`. Content is logged at INFO only when `LOG_TRANSLATION_CONTENT = True` in config.

## Validation

`validator.py:31` — checks `alphabetic_chars_in_target_script / total_alphabetic_chars >= 0.5`. Skips if target language has no script patterns defined. Cyrillic is the only script currently exercised.
