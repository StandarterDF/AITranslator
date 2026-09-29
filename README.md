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

### Windows
```batch
install.bat
start.bat
```

### Linux / macOS
```bash
chmod +x install.sh start.sh
./install.sh
./start.sh
```

Server starts at **http://0.0.0.0:5555**.

## 💻 CLI (direct start)

```bash
# Server using config.json in project root (or config.json.example fallback)
venv/bin/python main.py

# Server with a specific config file
venv/bin/python main.py --config configs/deepseek.json

# Choose a provider
venv/bin/python main.py --provider localllm

# Or set via environment variable
TRANSLATOR_PROVIDER=localllm venv/bin/python main.py

# Enable uvicorn auto-reload (development only; disabled by default)
venv/bin/python main.py --reload

# TUI (Textual terminal interface)
venv/bin/python tui.py
venv/bin/python tui.py --config configs/deepseek.json
```

On Windows with venv: `venv\Scripts\python main.py`.

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
| `static/index.html` | Web UI — Google Translate-style translation interface |
| `static/stats.html` | Stats dashboard (period-scoped charts) |
| `tui.py` | TUI — Textual-based server console (logs + status) |
| `translator.py` | `LLMTranslator` — fallback chain execution |
| `config.py` | Config loader (.env keys + config.json parsing) |
| `prompt_template.py` | Dynamic system/user prompt templates (any language pair) |
| `validator.py` | Script-based language validation (≥50% target script) |
| `markdown_guard.py` | Deterministic Markdown masking/restoration |
| `cache_manager.py` | SHA256 JSON cache in `cache/` directory, version stamps |
| `stats_manager.py` | JSONL event log + aggregated stats |

## ⚙️ Configuration

### .env — API keys only

`.env` (gitignored, copy from `.env.example`) holds **only API keys**. Variable names can be arbitrary — each name is referenced by the `api_key` field in `config.json`.

```
LOCALLLM_API_KEY=sk-LocalHost
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
LIBRETRANSLATE_API_KEY=
```

### config.json — launch configuration

`config.json` (gitignored, copy from `config.json.example`) defines providers, chain, and runtime settings.

**Key resolution for `api_key`:**
- If the value is a non-empty string that exists as an env var → the env var's value is used.
- If the env var is not set → the value is kept as a literal (useful for local servers, e.g. `"sk-LocalHost"`).

**Structure:**
```json
{
  "providers": {
    "deepseek": {
      "api_key": "DEEPSEEK_API_KEY",
      "base_url": "https://api.deepseek.com/v1",
      "model": "deepseek-v4-flash",
      "prefill": "",
      "api_type": "deepseek",
      "reasoning_effort": null
    }
  },
  "default_provider": "deepseek",
  "translation_chain": [
    {"type": "llm", "provider": "deepseek", "max_tokens": null}
  ],
  "libretranslate_url": "https://libretranslate.com/translate",
  "libretranslate_api_key": "",
  "preserve_markdown": true,
  "translate_fenced_code": true,
  "log_translation_content": false,
  "log_level": "INFO"
}
```

**Config file resolution priority:**
1. `TRANSLATOR_CONFIG` env var (absolute or relative to project root)
2. `config.json` in project root
3. `config.json.example` fallback (with warning)
4. Empty config (with error)

Ready-made minimal templates are in `configs/` (deepseek, localllm, deepseek+fallback). Copy the one you need to `config.json`.

- `log_level` — root logger level: `DEBUG`, `INFO` (default), `WARNING`, `ERROR`. `DEBUG` enables verbose logs (full openai-client request bodies, httpcore connection details).
- `preserve_markdown` (default `true`) — mask Markdown constructs with placeholders before sending to the model, restore them afterwards. Two passes: **block** (ATX heading markers, `---`/`***`/`___`/`===` rules, `───` box rules, `>` blockquotes, two-space hard breaks, `[text](url)` / `![alt](url)` brackets) and **inline** (emphasis, inline code, HTML tags/comments, URLs, fenced code). Heading text and link labels are still translated; only the markers are protected.
- `translate_fenced_code` (default `true`) — translate the text inside ``` ``` blocks (only the fence delimiters are masked). `false` masks the whole block verbatim.

### Reasoning effort

Provider default from `config.json` (`reasoning_effort` field). Runtime override via TUI `F2` cycles `low` → `high` → `max` → `off`. `off` (None) disables thinking.

Priority: `reasoning_state.json` > `config.json` (or `--config`) > `config.json.example` > empty.

## 🔗 Fallback chain

Defined in `config.json` as `translation_chain`. Each step is tried in order:

- ✅ **Success** → result cached and returned
- ❌ **Failure** → next step runs

**Two LLM modes:**

- 💬 **chat** (default): `chat.completions.create()` with system/user/assistant messages
- ⚡ **completions**: `completions.create()` with raw `<|channel|>`-token prompt (no prefill)

**API types per provider** (`api_type` in `providers`):

- 🔵 `openai` (default): OpenAI-compatible `chat.completions`, reasoning effort sent as `extra_body["reasoning_effort"]`
- 🔴 `deepseek`: native DeepSeek API, reasoning effort sent as top-level `"thinking": {"reasoning_effort": ...}`

**Non-LLM fallbacks:** `google` (free API), `libretranslate`.

## 🖥 Web UI

Browser-based translation interface (Google Translate style) at the root URL.

- `http://localhost:5555/` — two-panel UI with source/target language selectors, auto-translate with 2.5s debounce, swap button, copy to clipboard
- Supports every language in the validation list (auto-detect for source)
- 🌞 Light theme and 🌙 dark theme
- Served from `static/index.html`

| Light theme | Dark theme |
|---|---|
| <img alt="Web UI light" src="static/img/webui.jpg" width="450"> | <img alt="Web UI dark" src="static/img/webui_black.jpg" width="450"> |

## 🖥 TUI

Textual-based server console — runs the FastAPI server in a background thread and streams its logs.

- `python tui.py` — launches the TUI: live log viewer, status panel (config, chain, reasoning, port, session counters) and status bar
- Starts the FastAPI server automatically and restarts it on demand
- Keyboard-driven workflow:
  - `F2` — cycle reasoning effort for the default provider (`low` → `high` → `max` → `off`)
  - `F3` — restart the server
  - `F5` — clear the log
  - `F6` — copy the log to clipboard
  - `Ctrl+C` — quit (stops the server)
- Useful for server administration or headless environments

| TUI main screen |
|---|
| <img alt="TUI" src="static/TUI.jpg" width="600"> |

## 🌐 API Routes

| Method | Path | Description |
|---|---|---|
| 🟢 `GET` | `/` | Web UI (translation interface) |
| 🟢 `POST` | `/translate` | Translate text (`q`, `source`, `target`) |
| 🟢 `GET` | `/health` | Health check |
| 🔵 `GET` | `/cache` | List cache entries |
| 🔴 `DELETE` | `/cache/{hash_key}` | Delete single cache entry |
| 🟡 `POST` | `/cache/{hash_key}/invalidate` | Invalidate cache entry |
| 📊 `GET` | `/stats` | Stats dashboard (HTML) |
| 📊 `GET` | `/stats/api` | Aggregated stats JSON (`from`, `to` optional, YYYY-MM-DD) |
| 📁 `GET` | `/static/*` | Static assets |

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

## 💾 Cache versioning

Every cache entry records the pipeline version that produced it (`translator.TRANSLATOR_VERSION`). On a cache hit the stored translation is re-checked statically before it is served — no model call, just deterministic checks:

1. **Markers** — the source and the stored translation are both masked with the same rules and their Markdown markers are compared. Anything the source has and the translation lost (`*`, `**`, `---`, `##`, hard breaks, link brackets) fails the check. Markers the translation gained are ignored.
2. **Language** — the same 50% script check as fresh output.

| Stored entry | Static check | Result |
|---|---|---|
| passes | — | served; if its `version` is older, only the version field is restamped (`created_at` untouched) |
| fails | — | invalidated and re-translated, once per key per server run |
| fails again after a refresh | — | served from cache with a warning, rather than paying for the same text twice |

Entries written before versioning have no `version` field and are read as `0`, so they are simply stamped with the current version. Bumping `TRANSLATOR_VERSION` (new prompt, different model, new mask rule) therefore re-stamps good entries instead of re-translating them — only a failed check forces new work. TUI counts the rejected entries under `Stale`.

## 📦 Dependencies

```
fastapi    uvicorn    openai
pydantic   httpx      python-dotenv
textual    pytest
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

### Windows
```batch
install.bat
start.bat
```

### Linux / macOS
```bash
chmod +x install.sh start.sh
./install.sh
./start.sh
```

Сервер запускается на **http://0.0.0.0:5555**.

## 💻 CLI (прямой запуск)

```bash
# Сервер с config.json в корне проекта (или fallback на config.json.example)
venv/bin/python main.py

# Сервер с конкретным файлом конфигурации
venv/bin/python main.py --config configs/deepseek.json

# Выбор провайдера
venv/bin/python main.py --provider localllm

# Или через переменную окружения
TRANSLATOR_PROVIDER=localllm venv/bin/python main.py

# Включить автоперезагрузку uvicorn (только для разработки; по умолчанию выключена)
venv/bin/python main.py --reload

# TUI (терминальный интерфейс на Textual)
venv/bin/python tui.py
venv/bin/python tui.py --config configs/deepseek.json
```

В Windows с venv: `venv\Scripts\python main.py`.

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
| `static/index.html` | Web UI — интерфейс перевода в стиле Google Translate |
| `tui.py` | TUI — терминальный интерфейс перевода на Textual |
| `translator.py` | `LLMTranslator` — исполнение цепочки fallback |
| `config.py` | Загрузчик конфигурации (.env ключи + parsing config.json) |
| `prompt_template.py` | Динамический системный/пользовательский промпт (любая языковая пара) |
| `validator.py` | Валидация языка по скрипту (≥50% целевого алфавита) |
| `cache_manager.py` | SHA256 JSON-кэш в `cache/`, версии переводов |

## ⚙️ Конфигурация

### .env — только API-ключи

`.env` (gitignored, копируется из `.env.example`) содержит **только API-ключи**. Имя переменной может быть любым — на него ссылается поле `api_key` в `config.json`.

```
LOCALLLM_API_KEY=sk-LocalHost
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
LIBRETRANSLATE_API_KEY=
```

### config.json — конфигурация запуска

`config.json` (gitignored, копируется из `config.json.example`) определяет провайдеров, цепочку и настройки runtime.

**Разрешение `api_key`:**
- Если значение — непустая строка и существует как переменная окружения → подставляется значение из env.
- Если переменной нет → значение остаётся литералом (для локальных серверов, например `"sk-LocalHost"`).

**Структура:**
```json
{
  "providers": {
    "deepseek": {
      "api_key": "DEEPSEEK_API_KEY",
      "base_url": "https://api.deepseek.com/v1",
      "model": "deepseek-v4-flash",
      "prefill": "",
      "api_type": "deepseek",
      "reasoning_effort": null
    }
  },
  "default_provider": "deepseek",
  "translation_chain": [
    {"type": "llm", "provider": "deepseek", "max_tokens": null}
  ],
  "libretranslate_url": "https://libretranslate.com/translate",
  "libretranslate_api_key": "",
  "log_translation_content": false,
  "log_level": "INFO"
}
```

**Приоритет файла конфигурации:**
1. Переменная окружения `TRANSLATOR_CONFIG` (абсолютный или относительный путь)
2. `config.json` в корне проекта
3. `config.json.example` (с предупреждением)
4. Пустая конфигурация (с ошибкой)

Готовые минимальные шаблоны лежат в `configs/` (deepseek, localllm, deepseek+fallback). Скопируйте нужный в `config.json`.

- `log_level` — уровень логирования корневого логгера: `DEBUG`, `INFO` (по умолчанию), `WARNING`, `ERROR`. `DEBUG` включает подробные логи (полные тела запросов openai-клиента, connection-детали httpcore).
- `preserve_markdown` (по умолчанию `true`) — маскировать Markdown-разметку плейсхолдерами до отправки в модель и восстанавливать после. Два прохода: **блочный** (маркеры заголовков `#`, разделители `---`/`***`/`___`/`===`/`───`, цитаты `>`, перенос строки двумя пробелами, скобки `[текст](url)` / `![alt](url)`) и **инлайновый** (выделение, инлайн-код, HTML-теги/комментарии, URL, блоки кода). Текст заголовка и подпись ссылки при этом переводятся — защищаются только сами маркеры.
- `translate_fenced_code` (по умолчанию `true`) — переводить текст внутри блоков ``` ``` (маскируются только сами разделители). `false` — маскировать блок целиком.

### Режим мышления (reasoning effort)

Значение по умолчанию из `config.json` (`reasoning_effort`). Переключение в TUI по `F2`: `low` → `high` → `max` → `off`. `off` (None) отключает мышление.

Приоритет: `reasoning_state.json` > `config.json` (или `--config`) > `config.json.example` > пусто.

## 🔗 Цепочка fallback

Определяется в `config.json` как `translation_chain`. Шаги выполняются по порядку:

- ✅ **Успех** → результат кэшируется и возвращается
- ❌ **Неудача** → выполняется следующий шаг

**Два режима LLM:**

- 💬 **chat** (по умолчанию): `chat.completions.create()` с системным/пользовательским сообщением и префиллом
- ⚡ **completions**: `completions.create()` с сырым промптом и токенами `<|channel|>` (без префилла)

**Типы API провайдеров** (`api_type` в `providers`):

- 🔵 `openai` (по умолчанию): OpenAI-совместимые `chat.completions`, режим мышления уходит как `extra_body["reasoning_effort"]`
- 🔴 `deepseek`: нативный DeepSeek API, режим мышления уходит как top-level `"thinking": {"reasoning_effort": ...}`

**Не-LLM fallback:** `google` (бесплатный API), `libretranslate`.

## 🖥 Web UI

Интерфейс перевода в браузере (в стиле Google Translate) по корневому URL.

- `http://localhost:5555/` — двухпанельный интерфейс с выбором исходного/целевого языка, авто-перевод с задержкой 2.5с, кнопка смены языков, копирование в буфер
- Поддерживает все языки из списка валидации (авто-определение для исходного)
- 🌞 Светлая тема и 🌙 тёмная тема
- Файлы в `static/index.html`

| Светлая тема | Тёмная тема |
|---|---|
| <img alt="Web UI светлая" src="static/img/webui.jpg" width="450"> | <img alt="Web UI тёмная" src="static/img/webui_black.jpg" width="450"> |

## 🖥 TUI

Терминальная консоль сервера на базе Textual — запускает FastAPI сервер в фоновом потоке и транслирует его логи.

- `python tui.py` — запускает TUI: живой лог, панель статуса (конфиг, цепочка, режим мышления, порт, счётчики сессии) и статус-бар
- Автоматически запускает FastAPI сервер и перезапускает его по команде
- Управление с клавиатуры:
  - `F2` — циклическое переключение режима мышления для провайдера по умолчанию (`low` → `high` → `max` → `off`)
  - `F3` — перезапуск сервера
  - `F5` — очистка лога
  - `F6` — копирование лога в буфер обмена
  - `Ctrl+C` — выход (останавливает сервер)
- Удобно для администрирования сервера или окружений без браузера

| Главный экран TUI |
|---|
| <img alt="TUI" src="static/TUI.jpg" width="600"> |

## 🌐 API Routes

| Метод | Путь | Описание |
|---|---|---|
| 🟢 `GET` | `/` | Web UI (интерфейс перевода) |
| 🟢 `POST` | `/translate` | Перевод текста (`q`, `source`, `target`) |
| 🟢 `GET` | `/health` | Проверка работоспособности |
| 🔵 `GET` | `/cache` | Список записей кэша |
| 🔴 `DELETE` | `/cache/{hash_key}` | Удалить одну запись кэша |
| 🟡 `POST` | `/cache/{hash_key}/invalidate` | Инвалидировать запись кэша |
| 📊 `GET` | `/stats` | Дашборд статистики (HTML) |
| 📊 `GET` | `/stats/api` | JSON агрегированной статистики (`from`, `to` — опционально, YYYY-MM-DD) |
| 📁 `GET` | `/static/*` | Статические файлы |

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

## 💾 Версионирование кэша

Каждая запись кэша хранит версию конвейера, которая её создала (`translator.TRANSLATOR_VERSION`). При попадании в кэш сохранённый перевод повторно проверяется статически — без обращения к модели:

1. **Маркеры** — источник и сохранённый перевод маскируются одними и теми же правилами, затем сравниваются инвентари разметки. Всё, чего нет в переводе, но было в источнике (`*`, `**`, `---`, `##`, переносы двумя пробелами, скобки ссылок), считает проверку проваленной. Маркеры, которые перевод приобрёл, игнорируются.
2. **Язык** — та же проверка по 50% скрипта, что и для свежего вывода.

| Запись | Проверка | Результат |
|---|---|---|
| пройдена | — | отдаётся из кэша; если `version` старее, обновляется только поле `version` (`created_at` не трогается) |
| провалена | — | помечается невалидной и переводится заново, один раз на ключ за запуск сервера |
| провалена снова после обновления | — | отдаётся из кэша с предупреждением, вместо повторной оплаты того же текста |

Записи, сделанные до появления версий, поля `version` не содержат и читаются как `0` — им просто проставляется текущая версия. Поэтому сам bump `TRANSLATOR_VERSION` (новый промпт, другая модель, новое правило маскирования) перепроставляет хорошие записи, а не переводит их заново: новую работу создаёт только проваленная проверка. TUI показывает отклонённые записи счётчиком `Stale`.

## 📦 Зависимости

```
fastapi    uvicorn    openai
pydantic   httpx      python-dotenv
textual    pytest
```
