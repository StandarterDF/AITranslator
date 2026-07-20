# AILibreTranslater

Self-hosted translation microservice powered by LLMs with a configurable fallback chain.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env with your API keys
python main.py
```

Server starts at `http://0.0.0.0:5555`.

## Usage

```bash
curl -X POST http://localhost:5555/translate \
  -H "Content-Type: application/json" \
  -d '{"q": "Hello world", "source": "auto", "target": "ru"}'
```

## Architecture

| File | Role |
|---|---|
| `main.py` | FastAPI app, routes, uvicorn launcher |
| `translator.py` | `LLMTranslator` — fallback chain execution |
| `config.py` | Providers, chain definition, presets |
| `prompt_template.py` | System/user prompt templates (en→ru) |
| `validator.py` | Script-based language validation (≥50% target script) |
| `cache_manager.py` | SHA256 JSON cache in `cache/` directory |

## Configuration

Set via `.env` or environment variables:

| Variable | Default | Description |
|---|---|---|
| `LOCALLLM_API_KEY` | `sk-LocalHost` | API key for local LLM |
| `LOCALLLM_BASE_URL` | `http://192.168.0.124:8080/v1` | OpenAI-compatible endpoint |
| `LOCALLLM_MODEL` | `QwenCoder` | Model name |
| `DEEPSEEK_API_KEY` | — | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | DeepSeek endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek model |
| `LIBRETRANSLATE_URL` | `https://libretranslate.com/translate` | LibreTranslate endpoint |
| `LOG_TRANSLATION_CONTENT` | `false` | Log translated text |

Provider selection: `python main.py --provider localllm` or `TRANSLATOR_PROVIDER=localllm`.

Preset selection: `python main.py --preset deepseek`. Interactive choice on startup if none given.

## Fallback chain

Defined in `config.py` as `TRANSLATION_CHAIN`. Each step is tried in order. On success — result is cached and returned. On failure — next step runs.

Two LLM modes:

- **chat** (default): `chat.completions.create()` with system/user/assistant messages
- **completions**: `completions.create()` with raw `<|channel|>`-token prompt (no prefill)

Non-LLM fallbacks: `google` (free API), `libretranslate`.

## API Routes

| Method | Path | Description |
|---|---|---|
| `POST` | `/translate` | Translate text (`q`, `source`, `target`) |
| `GET` | `/cache` | List cache entries |
| `DELETE` | `/cache/{hash_key}` | Delete single cache entry |
| `DELETE` | `/cache` | Clear all cache |

## Validation

Output is validated per language script (Cyrillic for ru/uk/be/bg/sr, CJK for zh/ja, etc.). At least 50% of alphabetic characters must match the target script. Falls through (always valid) for unsupported languages.

## Notes

- LLM steps hardcode source→target as **en→ru**. Non-LLM fallbacks use the original request params.
- `max_tokens` is dynamic: `input_chars / 4 * multiplier`, clamped to `[256, cap]`. Set `"max_tokens": null` to disable.

## Dependencies

`fastapi`, `uvicorn`, `openai`, `pydantic`, `httpx`, `python-dotenv`.
