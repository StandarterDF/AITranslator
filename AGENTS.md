# AILibreTranslater — agent guide

## Entrypoint & run

- `python main.py` — starts FastAPI on `0.0.0.0:5555` (uvicorn `reload` is **off** by default)
- `python main.py --reload` — starts FastAPI with uvicorn auto-reload enabled (development only)
- `start.bat` — alias for `python main.py`
- `docker compose up -d` — the same server in a container (`Dockerfile`, `docker-compose.yml`); `./cache` and `./stats` are bind mounts so runtime data survives `down`, `config.json` is mounted read-only, `.env` is injected via `env_file` and never baked into the image (`.dockerignore`). Start it as `UID=$(id -u) GID=$(id -g) docker compose up -d`, otherwise cache files become root-owned. No TUI in the container: `tui.py` runs its own server in-process. The service uses `network_mode: host` instead of a published port — SillyTavern sends outbound requests through a SOCKS5 proxy (`requestProxy` in its `config.yaml`), which refuses to connect to a Docker-published port on the host's own LAN IP; on the host network the app listens on `5555` directly, the same shape as the plain-python run, so the proxy's hairpin never goes through Docker NAT. An alternative/complement is adding the server's LAN address to SillyTavern's `requestProxy.bypass`.
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
markdown_guard.py — deterministic Markdown masking/restoration (block + inline passes)
cache_manager.py — SHA256 JSON cache in cache/ + translator version stamps
stats_manager.py — JSONL event log + aggregated stats
tui.py           — Textual TUI (server console)
temporary/       — scratch analysis scripts (gitignored, not part of the app)
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
- **Two mask passes** (`markdown_guard.mask_markdown`): the **block pass** runs first over the text *outside* fenced code and masks line-leading markers — ATX heading `## ` and its closing ` ###`, thematic break `---`/`***`/`___`/`- - -`, setext `===`, blockquote `>`, two-space hard break, box-drawing rules `───`/`═══` (U+2500–U+257F), and the brackets of `[text](url)` / `![alt](url)`. Link text stays visible and gets translated; an **image is masked whole, alt text included** — the alt is not rendered, and a two-placeholder pair with a word between them at the end of a text is the shape models drop. Then the **inline pass** masks HTML comments/tags, URLs, `` `code` ``, `\*` runs and fences. Both passes share one token counter, so indices are unique but not in document order.
- **A line-structural token never contains a line ending.** The break after `---` stays in the text so the placeholder occupies a line of its own; if the token ate the newline the placeholder was glued to the next line and the model could not tell it was a separator — that is where rules were lost. It also makes tokens EOL-agnostic, so a CRLF source and an LF translation produce identical tokens and `cached_defect` stops flagging intact rules.
- **A rule or image that ends the source is remembered separately** (`MaskedText.trailing` = token indices, separator, construct, closing whitespace) and re-appended in `restore_markdown` when the model drops it — a construct reduced to a bare placeholder on the last line is the spot models reliably lose. The whitespace is the source's own bytes, so the re-appended piece is identical to the source (a blank line before a rule stays a blank line, a setext underline stays an underline). **Only a construct that vanished entirely is re-appended**: half a link would come back with its label twice, and that is no better than a loss — `missing_placeholders` reports either case. A *middle* construct that gets dropped is only logged, never moved to the end.
- **Inline patterns are compiled per call** (`_build_inline_regexes`): the block pass leaves `{{0}}`-markers behind and the URL pattern has no delimiter that would stop at them, so the URL body gets a `(?!{{)` guard — otherwise a URL swallows the marker after it and that marker is lost on restore. Fuzz `temporary/fuzz_mask.py` checks this invariant; do not relax it.
- **Block tokens are flagged structural**: `MaskedText.structural[i]` / `is_structural(i)`. A lost structural marker (heading, rule, quote, link bracket) means the translation lost document structure; a lost inline marker is only cosmetic. `translator._log_missing_markers` logs the two groups separately — **warn only, the step still succeeds**.
- **`has_markdown()` covers block constructs too**, otherwise a text whose only Markdown is a heading or `---` would not be masked at all.
- **Not protected** (still model-visible): list markers `- `/`1. `, tables, `~~strike~~`, `_underscore_` emphasis, reference links `[ref]: url`, and the label of a lone `[bracket]` without `(url)`.
- **Line endings belong to the source.** `translator.restore_line_endings(source, translation)` (next to `restore_urls`) gives the output the source's dominant ending, because a model normalises CRLF to LF on its own and SillyTavern renders the two differently. It runs both on the success path and on the cache-hit path: `cache_manager._cache_key` normalises line endings, so one entry serves CRLF and LF requests and each must get its own back. A genuinely mixed source returns `None` from `source_line_ending` and is left alone.
- **Never strip the request or the reply's edges.** `translator.restore_surrounding_whitespace` puts the source's own leading/trailing whitespace back, applied by `_finish` to fresh output and to cache hits alike. SillyTavern's built-in translate extension splits a message at every `![img](url)`, translates each piece **separately** and re-inserts the links itself **with no separator** (`public/scripts/extensions/translate/index.js`, "split text by embedded images links"). So the piece it sends ends with the blank line that separated the text from the image, and a stripped reply glues the link onto the last line: `---![img](url)` is neither a rule nor a block of its own, and the `---` renders as literal dashes. `main.py` therefore passes `q` unstripped (the emptiness check still uses `q.strip()`), and `_cache_key` strips anyway, so no existing entry misses.
- **The client never receives the image in the request.** Because of that split, an image inside a SillyTavern message is *not* part of what any provider is asked to translate — ST puts it back itself. Don't chase a "lost image" in the cache: `source_text` is the request verbatim, and the request-log line `N markdown image(s)` (`main.py`) says outright whether one arrived.
## Cache

- **DO NOT clear entire cache**. Only delete specific corrupt entries.
- Cache entries are JSON files in `cache/` directory, named by hash key.
- To delete a single entry: `python -c "import cache_manager; cache_manager.delete_cache('HASH_KEY')"` (full hash from log or file name).
- Log shows a truncated hash on cache hits: `Cached translation <first-12-hex>`.
- The FastAPI app exposes `DELETE /cache/{hash_key}` (single entry) and `POST /cache/{hash_key}/invalidate`; there is **no** clear-all route.
- `GET /cache` lists all entries with previews to find the right hash.
- **Versioned cache**: every entry carries `"version"` = `translator.TRANSLATOR_VERSION`. On a cache hit the entry is re-checked by `translator.cached_defect(source, cached, target)`; on a pass it is reused and only the `version` field is re-stamped (`cache_manager.set_version`, `created_at` untouched so `/cache` ordering survives). Entries written before versioning simply have no field and are read as `version=0` — they pass the check and get the current stamp.
- **The static check is mask-vs-mask**: both the source and the stored translation go through `markdown_guard.mask_markdown`, and the two token multisets are compared one-way (`Counter(source) - Counter(cached)`). A stored translation has already been restored, so its placeholders are gone — comparing placeholders would be wrong. Markers the translation *gained* are ignored. Tokens must stay free of `\r`/`\n`, otherwise a CRLF source never matches an LF translation and intact entries get re-translated.
- **A token must be stable across the request, not just present.** An image token contains its alt text, which is no longer translated, so a source image and its translation produce the same token; had the alt stayed translatable, every old entry with an image would report a false defect and be re-translated once.
- **A failed check re-translates, but only once per key per process** (`LLMTranslator._refreshed`). Without that guard a model that consistently drops a marker would re-pay for every request. The second failure is logged and the cache is served. TUI shows the count as `Stale`.
- **Bump `TRANSLATOR_VERSION`** when a change makes old translations suspect (new prompt, different model, new mask rule). A bump alone re-stamps instead of re-translating: only `cached_defect` forces a refresh. Currently **2** (block-marker masking + line endings); the version history lives in the comment above the constant. On the current cache a bump would stamp 280 entries and refresh 147.

## Dependencies

`requirements.txt` — `fastapi`, `uvicorn`, `openai`, `pydantic`, `httpx`, `python-dotenv`, `textual` (+ `pytest` for tests). `httpx` is only used by Google/LibreTranslate fallback functions; not required for pure-LLM chains.

## Logging

Root logger level is set by `log_level` in `config.json` (default `INFO`). `DEBUG` enables verbose logs (full request bodies, httpcore connection details). `httpx`/`httpcore` are always throttled to `WARNING`. Content is logged at INFO only when `LOG_TRANSLATION_CONTENT = True` in config.

## Validation

`validator.py` — checks `alphabetic_chars_in_target_script / total_alphabetic_chars >= 0.5` (single pass over the string). Skips (returns `True`) if the target language has no script patterns defined. Patterns exist for Cyrillic (`ru`/`uk`/`be`/`bg`/`sr`), CJK (`zh`/`ja`/`ko`), Arabic, Hebrew, Thai, Greek, Devanagari, and many Latin-script languages. Fenced code blocks are stripped before validation via `_validation_text`/`without_fenced_blocks`.
