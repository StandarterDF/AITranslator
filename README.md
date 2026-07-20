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

---

# AILibreTranslater

Самописный микросервис перевода на базе LLM с настраиваемой цепочкой fallback.

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env
# отредактируйте .env, указав свои API-ключи
python main.py
```

Сервер запускается на `http://0.0.0.0:5555`.

## Использование

```bash
curl -X POST http://localhost:5555/translate \
  -H "Content-Type: application/json" \
  -d '{"q": "Hello world", "source": "auto", "target": "ru"}'
```

## Архитектура

| Файл | Роль |
|---|---|
| `main.py` | FastAPI приложение, роуты, запуск uvicorn |
| `translator.py` | `LLMTranslator` — исполнение цепочки fallback |
| `config.py` | Провайдеры, цепочка перевода, пресеты |
| `prompt_template.py` | Системный/пользовательский промпт (en→ru) |
| `validator.py` | Валидация языка по скрипту (≥50% целевого алфавита) |
| `cache_manager.py` | SHA256 JSON-кэш в директории `cache/` |

## Конфигурация

Задаётся через `.env` или переменные окружения:

| Переменная | По умолчанию | Описание |
|---|---|---|
| `LOCALLLM_API_KEY` | `sk-LocalHost` | API-ключ для локальной LLM |
| `LOCALLLM_BASE_URL` | `http://192.168.0.124:8080/v1` | OpenAI-совместимый эндпоинт |
| `LOCALLLM_MODEL` | `QwenCoder` | Название модели |
| `DEEPSEEK_API_KEY` | — | API-ключ DeepSeek |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | Эндпоинт DeepSeek |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Модель DeepSeek |
| `LIBRETRANSLATE_URL` | `https://libretranslate.com/translate` | Эндпоинт LibreTranslate |
| `LOG_TRANSLATION_CONTENT` | `false` | Логировать текст перевода |

Выбор провайдера: `python main.py --provider localllm` или `TRANSLATOR_PROVIDER=localllm`.

Выбор пресета: `python main.py --preset deepseek`. Интерактивный выбор при запуске, если пресет не указан.

## Цепочка fallback

Определяется в `config.py` как `TRANSLATION_CHAIN`. Шаги выполняются по порядку. При успехе — результат кэшируется и возвращается. При неудаче — выполняется следующий шаг.

Два режима LLM:

- **chat** (по умолчанию): `chat.completions.create()` с системным/пользовательским сообщением и префиллом ассистента
- **completions**: `completions.create()` с сырым промптом с токенами `<|channel|>` (без префилла)

Не-LLM fallback: `google` (бесплатный API), `libretranslate`.

## API Routes

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/translate` | Перевод текста (`q`, `source`, `target`) |
| `GET` | `/cache` | Список записей кэша |
| `DELETE` | `/cache/{hash_key}` | Удалить одну запись кэша |
| `DELETE` | `/cache` | Очистить весь кэш |

## Валидация

Результат проверяется по алфавиту целевого языка (кириллица для ru/uk/be/bg/sr, CJK для zh/ja и т.д.). Не менее 50% буквенных символов должны относиться к целевому скрипту. Для неподдерживаемых языков валидация пропускается.

## Заметки

- LLM-шаги жёстко задают source→target как **en→ru**. Не-LLM fallback используют оригинальные параметры запроса.
- `max_tokens` вычисляется динамически: `input_chars / 4 * multiplier`, в диапазоне `[256, cap]`. Установите `"max_tokens": null` для отключения лимита.

## Зависимости

`fastapi`, `uvicorn`, `openai`, `pydantic`, `httpx`, `python-dotenv`.
