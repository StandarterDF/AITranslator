# AILibreTranslater — agent guide

## Entrypoint & run

- `python main.py` — starts FastAPI on `0.0.0.0:5555` (uvicorn `reload` is **off** by default)
- `python main.py --reload` — starts FastAPI with uvicorn auto-reload enabled (development only)
- `start.bat` — alias for `python main.py`
- Main route: `POST /translate` — expects `q` (text), `source` (default `"auto"`), `target` (required). Also `GET /health`, `GET /cache`, `DELETE /cache/{hash_key}`, `POST /cache/{hash_key}/invalidate`, `GET /stats`, `GET /stats/api`, `GET /` + `/static/*`.
- Provider selection: `TRANSLATOR_PROVIDER` env var or `--provider <name>` → overrides `config.DEFAULT_PROVIDER`.
- Config file: `--config <path>` CLI arg or `TRANSLATOR_CONFIG` env var

## Architecture

Flat single-module project (no `__init__.py`, no packages).

```
translator.py    — LLMTranslator + fallback chain logic
config.py        — config loader (.env keys + config.json parsing)
main.py          — FastAPI app + uvicorn launcher
prompt_template.py — dynamic system/user prompt templates (any language pair)
validator.py     — script-based language validation (≥50% target script)
markdown_guard.py — deterministic Markdown masking/restoration
cache_manager.py — SHA256 JSON cache in cache/
stats_manager.py — JSONL event log + aggregated stats
tui.py           — Textual TUI (server console)
```

## Key quirks

- **config.py is a pure loader**: reads `.env` (via `python-dotenv`) and `config.json`. No hardcoded providers or defaults. `api_key` values in JSON are env var NAMES — resolved at load time. Literal kept if env var missing.
- **Config file resolution**: `TRANSLATOR_CONFIG` env → `config.json` in root → `config.json.example` fallback (with warning) → empty config (with error). `--config` CLI arg sets `TRANSLATOR_CONFIG` before import.
- **Priority**: `reasoning_state.json` > `config.json` (or `--config`) > `config.json.example` > empty.
- **source/target are dynamic**: LLM steps translate the requested `source`/`target` pair (default source `"auto"`). `prompt_template.format_prompt(source, target, text)` builds the system/user prompt from `LANGUAGE_NAMES`; the system prompt itself is written in Russian and appends Russian-specific rules when `target == "ru"`.
- **Chain fallback**: `LLMTranslator.__init__` uses `config.TRANSLATION_CHAIN`; if it is empty, it falls back to `_default_chain()` (default provider + `google` + `libretranslate`). `--provider`/`TRANSLATOR_PROVIDER` overrides `config.DEFAULT_PROVIDER`.
- **Fallback chain**: `config.json` → `translation_chain` — ordered list of steps. Each step can be an LLM (with provider, prefill, temperature, multiplier overrides) or a non-LLM translator.
- **Dynamic max_tokens**: `input_chars / 4 * multiplier`, clamped to `[256, cap]`. Set per-step in `translation_chain` (`multiplier`, `cap`). Set `"max_tokens": null` to remove the limit entirely.
- **prefill logic**: If `"prefill"` key is present in step — use that value (can be `None` to disable). If absent — fall back to provider's `prefill` from `PROVIDERS`.
- **API type per provider**: `cfg["api_type"]` in `PROVIDERS` — `"openai"` (default, OpenAI-compatible chat.completions) or `"deepseek"` (native DeepSeek API). For `"deepseek"` the reasoning is sent as top-level `"thinking": {"type": "enabled"|"disabled", "reasoning_effort": ...}`; for `"openai"` as `extra_body["reasoning_effort"]`.
- **Reasoning effort is runtime-mutable**: provider default from `config.json` (`reasoning_effort`). TUI F2 cycles low→high→max→off for `config.DEFAULT_PROVIDER` via `LLMTranslator.toggle_reasoning()` — applied on the next request, no server restart needed. `off` (None) sends `thinking: {"type": "disabled"}` for deepseek and omits `reasoning_effort` for openai. Step-level `"reasoning_effort"` in the chain overrides everything.
- **Step 1 — chat mode (DO NOT TOUCH)**: `"mode": "chat"` (default). Uses `client.chat.completions.create()` with system+user+assistant prefill. The provider's default prefill (`<|channel|>thought...`) works. This step is stable and must not be modified.
- **Step 2 — completions mode**: `"mode": "completions"`. Uses `client.completions.create(prompt=...)` — raw prompt with `<|channel|>` tokens, no prefill, no messages. The model outputs `<|channel|>thought\n...<|channel|>\n...translation...`. Parsing strips the thought block via `split("<|channel|>")[-1]`.
- **Step 2 NEVER uses prefill** — it's a raw completions request. The model reasons naturally in a thought block, then outputs the answer.
- **Output cleaning**: no regex trigger list. Each LLM branch strips a leading prefill (chat mode), and if `\n\nПеревод:` is found in the output everything before it is discarded (guards against English paraphrase). Target-language validation then decides pass/fail.
- **`translate_fenced_code`** (config, default `true`): fenced code block delimiters (```) become placeholders but the *content between them stays visible* — so text inside ``` blocks is translated. Set `false` to mask whole blocks verbatim (old behaviour). Inline code (`` `x` ``) is always masked whole. `markdown_guard.mask_markdown(text, translate_fenced=...)` drives this; `markdown_guard.markdown_instruction(masked, translate_fenced=...)` appends a clarifying line about code-block markers.
- **Validation skips fenced code**: `validate_translation` is run on `_validation_text` (translator.py) — `markdown_guard.without_fenced_blocks()` strips ```...``` blocks first, because code may legitimately stay in the source script (identifiers/strings). Only the surrounding prose is checked against the target language.
## Cache

- **DO NOT clear entire cache**. Only delete specific corrupt entries.
- Cache entries are JSON files in `cache/` directory, named by hash key.
- To delete a single entry: `python -c "import cache_manager; cache_manager.delete_cache('HASH_KEY')"` (full hash from log or file name).
- Log shows a truncated hash on cache hits: `Cached translation <first-12-hex>`.
- The FastAPI app exposes `DELETE /cache/{hash_key}` (single entry) and `POST /cache/{hash_key}/invalidate`; there is **no** clear-all route.
- `GET /cache` lists all entries with previews to find the right hash.

## Dependencies

`requirements.txt` — `fastapi`, `uvicorn`, `openai`, `pydantic`, `httpx`, `python-dotenv`, `textual` (+ `pytest` for tests). `httpx` is only used by Google/LibreTranslate fallback functions; not required for pure-LLM chains.

## Logging

Root logger level is set by `log_level` in `config.json` (default `INFO`). `DEBUG` enables verbose logs (full request bodies, httpcore connection details). `httpx`/`httpcore` are always throttled to `WARNING`. Content is logged at INFO only when `LOG_TRANSLATION_CONTENT = True` in config.

## Validation

`validator.py` — checks `alphabetic_chars_in_target_script / total_alphabetic_chars >= 0.5` (single pass over the string). Skips (returns `True`) if the target language has no script patterns defined. Patterns exist for Cyrillic (`ru`/`uk`/`be`/`bg`/`sr`), CJK (`zh`/`ja`/`ko`), Arabic, Hebrew, Thai, Greek, Devanagari, and many Latin-script languages. Fenced code blocks are stripped before validation via `_validation_text`/`without_fenced_blocks`.
