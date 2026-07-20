<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/LLM-OpenAI--compatible-FF6F00?style=for-the-badge&logo=openai" alt="LLM">
  <img src="https://img.shields.io/badge/status-active-brightgreen?style=for-the-badge" alt="Status">
</p>

# AILibreTranslater

> Self-hosted translation microservice powered by LLMs with a configurable fallback chain.

---

## 🚀 Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env with your API keys
python main.py
```

Server starts at **http://0.0.0.0:5555**.

## 📦 Usage

```bash
curl -X POST http://localhost:5555/translate \
  -H "Content-Type: application/json" \
  -d '{"q": "Hello world", "source": "auto", "target": "ru"}'
```

## 🧱 Architecture

| File | Role |
|---|---|
| `main.py` | FastAPI app, routes, uvicorn launcher |
| `translator.py` | `LLMTranslator` — fallback chain execution |
| `config.py` | Providers, chain definition, presets |
| `prompt_template.py` | Dynamic system/user prompt templates (any language pair) |
| `validator.py` | Script-based language validation (≥50% target script) |
| `cache_manager.py` | SHA256 JSON cache in `cache/` directory |

## ⚙️ Configuration

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

## 🔗 Fallback chain

Defined in `config.py` as `TRANSLATION_CHAIN`. Each step is tried in order:

- ✅ **Success** → result cached and returned
- ❌ **Failure** → next step runs

**Two LLM modes:**

- 💬 **chat** (default): `chat.completions.create()` with system/user/assistant messages
- ⚡ **completions**: `completions.create()` with raw `<|channel|>`-token prompt (no prefill)

**Non-LLM fallbacks:** `google` (free API), `libretranslate`.

## 🌐 API Routes

| Method | Path | Description |
|---|---|---|
| 🟢 `POST` | `/translate` | Translate text (`q`, `source`, `target`) |
| 🟢 `GET` | `/health` | Health check |
| 🔵 `GET` | `/cache` | List cache entries |
| 🔴 `DELETE` | `/cache/{hash_key}` | Delete single cache entry |
| 🟡 `POST` | `/cache/{hash_key}/invalidate` | Invalidate cache entry |

## ✅ Validation

Output is validated per language script. At least **50%** of alphabetic characters must match the target script:

- 🇷🇺 Cyrillic — ru, uk, be, bg, sr
- 🇨🇳 CJK — zh, ja, ko
- 🇸🇦 Arabic — ar
- 🇮🇱 Hebrew — he
- 🇹🇭 Thai — th
- 🇬🇷 Greek — el
- 🇮🇳 Devanagari — hi
- 🔤 Latin — en, es, fr, de, it, pt, nl, pl, tr, vi, cs, sv, da, fi, id, ms, no, ro, hu

Falls through (always valid) for unsupported languages.

## 📦 Dependencies

```
fastapi    uvicorn    openai
pydantic   httpx      python-dotenv
```

---

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/LLM-OpenAI--compatible-FF6F00?style=for-the-badge&logo=openai" alt="LLM">
  <img src="https://img.shields.io/badge/status-active-brightgreen?style=for-the-badge" alt="Status">
</p>

# AILibreTranslater

> Самописный микросервис перевода на базе LLM с настраиваемой цепочкой fallback.

---

## 🚀 Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env
# отредактируйте .env, указав свои API-ключи
python main.py
```

Сервер запускается на **http://0.0.0.0:5555**.

## 📦 Использование

```bash
curl -X POST http://localhost:5555/translate \
  -H "Content-Type: application/json" \
  -d '{"q": "Hello world", "source": "auto", "target": "ru"}'
```

## 🧱 Архитектура

| Файл | Роль |
|---|---|
| `main.py` | FastAPI приложение, роуты, запуск uvicorn |
| `translator.py` | `LLMTranslator` — исполнение цепочки fallback |
| `config.py` | Провайдеры, цепочка перевода, пресеты |
| `prompt_template.py` | Динамический системный/пользовательский промпт (любая языковая пара) |
| `validator.py` | Валидация языка по скрипту (≥50% целевого алфавита) |
| `cache_manager.py` | SHA256 JSON-кэш в `cache/` |

## ⚙️ Конфигурация

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

## 🔗 Цепочка fallback

Определяется в `config.py` как `TRANSLATION_CHAIN`. Шаги выполняются по порядку:

- ✅ **Успех** → результат кэшируется и возвращается
- ❌ **Неудача** → выполняется следующий шаг

**Два режима LLM:**

- 💬 **chat** (по умолчанию): `chat.completions.create()` с системным/пользовательским сообщением и префиллом
- ⚡ **completions**: `completions.create()` с сырым промптом и токенами `<|channel|>` (без префилла)

**Не-LLM fallback:** `google` (бесплатный API), `libretranslate`.

## 🌐 API Routes

| Метод | Путь | Описание |
|---|---|---|
| 🟢 `POST` | `/translate` | Перевод текста (`q`, `source`, `target`) |
| 🟢 `GET` | `/health` | Проверка работоспособности |
| 🔵 `GET` | `/cache` | Список записей кэша |
| 🔴 `DELETE` | `/cache/{hash_key}` | Удалить одну запись кэша |
| 🟡 `POST` | `/cache/{hash_key}/invalidate` | Инвалидировать запись кэша |

## ✅ Валидация

Результат проверяется по алфавиту целевого языка. Не менее **50%** буквенных символов должны относиться к целевому скрипту:

- 🇷🇺 Кириллица — ru, uk, be, bg, sr
- 🇨🇳 CJK — zh, ja, ko
- 🇸🇦 Арабский — ar
- 🇮🇱 Иврит — he
- 🇹🇭 Тайский — th
- 🇬🇷 Греческий — el
- 🇮🇳 Деванагари — hi
- 🔤 Латиница — en, es, fr, de, it, pt, nl, pl, tr, vi, cs, sv, da, fi, id, ms, no, ro, hu

Для неподдерживаемых языков валидация пропускается.

## 📦 Зависимости

```
fastapi    uvicorn    openai
pydantic   httpx      python-dotenv
```
