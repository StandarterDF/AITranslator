import json
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REASONING_STATE_FILE = Path(__file__).parent / "reasoning_state.json"

# "openai"  — OpenAI-compatible chat.completions (messages, reasoning_effort in extra_body)
# "deepseek" — native DeepSeek API (top-level "thinking": {"reasoning_effort": ...})
API_TYPES = ("openai", "deepseek")

REASONING_EFFORT_LEVELS = ("low", "high", "max")


def _parse_reasoning_effort(value: str | None) -> str | None:
    """'off'/'none'/пусто/None -> None (мышление выключено); иначе строка как есть."""
    if value is None or value.strip().lower() in ("", "off", "none"):
        return None
    return value


PROVIDERS: dict[str, dict] = {
    "localllm": {
        "api_key": os.getenv("LOCALLLM_API_KEY", "sk-LocalHost"),
        "base_url": os.getenv("LOCALLLM_BASE_URL", "http://192.168.0.124:8080/v1"),
        "model": os.getenv("LOCALLLM_MODEL", "QwenCoder"),
        "prefill": os.getenv(
            "LOCALLLM_PREFILL",
            "<|channel|>thought\nМоя задача — перевести текст с английского на русский языки. Я выдаю ТОЛЬКО перевод, без пояснений и оригинального текста. Сохраняю всю пунктуацию. <|channel|>",
        ),
    },
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "prefill": os.getenv("DEEPSEEK_PREFILL", ""),
        "api_type": os.getenv("DEEPSEEK_API_TYPE", "openai"),
        "reasoning_effort": _parse_reasoning_effort(
            os.getenv("DEEPSEEK_REASONING_EFFORT", "off")
        ),
    },
}

DEFAULT_PROVIDER = "localllm"

TRANSLATION_CHAIN: list[dict] = [
    {"type": "llm", "provider": "localllm", "multiplier": 8, "cap": 16384},
    {
        "type": "llm",
        "provider": "localllm",
        "mode": "completions",
        "temperature": 0.3,
        "multiplier": 10,
        "cap": 32768,
    },
]

LIBRETRANSLATE_URL = os.getenv(
    "LIBRETRANSLATE_URL", "https://libretranslate.com/translate"
)
LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "")

LOG_TRANSLATION_CONTENT = (
    os.getenv("LOG_TRANSLATION_CONTENT", "false").lower() == "true"
)

PRESETS: dict[str, dict] = {
    "default": {
        "name": "Default (Local LLM)",
        "description": "Local Qwen model via chat then completions fallback",
        "default_provider": "localllm",
        "translation_chain": [
            {"type": "llm", "provider": "localllm", "multiplier": 8, "cap": 16384},
            {
                "type": "llm",
                "provider": "localllm",
                "mode": "completions",
                "temperature": 0.3,
                "multiplier": 10,
                "cap": 32768,
            },
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "description": "DeepSeek API for translation with Google/LibreTranslate fallback",
        "default_provider": "deepseek",
        "translation_chain": [
            {"type": "llm", "provider": "deepseek", "max_tokens": None},
            {"type": "google"},
        ],
    },
}

_LOCAL_CONFIG_FILE = Path(__file__).parent / "config.json"


def _apply_config_overrides(preset: dict) -> None:
    """Apply a config dict (from preset or config.json) onto module globals.
    Used by both apply_preset() and _load_local_config().
    """
    global PROVIDERS, DEFAULT_PROVIDER, TRANSLATION_CHAIN
    global LIBRETRANSLATE_URL, LIBRETRANSLATE_API_KEY, LOG_TRANSLATION_CONTENT

    if "providers" in preset:
        for name, cfg in preset["providers"].items():
            if name in PROVIDERS:
                PROVIDERS[name].update(cfg)
            else:
                PROVIDERS[name] = cfg
        logger.debug("Applied %d providers from config", len(preset["providers"]))

    if "default_provider" in preset:
        DEFAULT_PROVIDER = preset["default_provider"]

    if "translation_chain" in preset:
        TRANSLATION_CHAIN = preset["translation_chain"]

    if "libretranslate_url" in preset:
        LIBRETRANSLATE_URL = preset["libretranslate_url"]

    if "libretranslate_api_key" in preset:
        LIBRETRANSLATE_API_KEY = preset["libretranslate_api_key"]

    if "log_translation_content" in preset:
        val = preset["log_translation_content"]
        LOG_TRANSLATION_CONTENT = (
            str(val).lower() in ("true", "1", "yes")
            if not isinstance(val, bool)
            else val
        )


def _load_local_config() -> None:
    """Load user-local config.json (gitignored) and merge into module globals.
    Priority: config.json overrides env-based defaults.
    reasoning_state.json still overrides reasoning_effort afterwards.
    """
    if not _LOCAL_CONFIG_FILE.exists():
        return

    try:
        raw = json.loads(_LOCAL_CONFIG_FILE.read_text("utf-8"))
    except (OSError, ValueError) as e:
        logger.warning(
            "Failed to parse %s: %s — keeping defaults", _LOCAL_CONFIG_FILE, e
        )
        return

    if not isinstance(raw, dict):
        logger.warning(
            "%s root is not a JSON object — keeping defaults", _LOCAL_CONFIG_FILE
        )
        return

    _apply_config_overrides(raw)
    logger.debug("Loaded local config from %s", _LOCAL_CONFIG_FILE)


_load_local_config()


def _load_reasoning_state() -> dict:
    try:
        data = json.loads(REASONING_STATE_FILE.read_text("utf-8"))
        state = data.get("reasoning_effort", {}) if isinstance(data, dict) else {}
        return {k: v for k, v in state.items() if isinstance(v, (str, type(None)))}
    except (OSError, ValueError):
        return {}


def _save_reasoning_state(state: dict) -> None:
    try:
        REASONING_STATE_FILE.write_text(
            json.dumps({"reasoning_effort": state}, ensure_ascii=False, indent=2),
            "utf-8",
        )
    except OSError as e:
        logger.warning("Failed to persist reasoning state: %s", e)


_reasoning_state = _load_reasoning_state()
for _provider, _effort in _reasoning_state.items():
    if _provider in PROVIDERS:
        PROVIDERS[_provider]["reasoning_effort"] = _effort


def list_presets() -> list[dict]:
    return [
        {
            "key": key,
            "name": p.get("name", key),
            "description": p.get("description", ""),
        }
        for key, p in PRESETS.items()
    ]


def get_reasoning_effort(provider: str) -> str | None:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return None
    return cfg.get("reasoning_effort")


def set_reasoning_effort(provider: str, effort: str | None) -> None:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Unknown provider '{provider}'")
    cfg["reasoning_effort"] = effort
    state = _load_reasoning_state()
    state[provider] = effort
    _save_reasoning_state(state)


def load_preset(name: str) -> dict | None:
    if name not in PRESETS:
        logger.error("Preset '%s' not found. Available: %s", name, list(PRESETS.keys()))
        return None
    return dict(PRESETS[name])


def apply_preset(preset: dict) -> None:
    """Apply a preset dict onto module globals."""
    _apply_config_overrides(preset)
    logger.debug("Applied preset '%s'", preset.get("name", "<unnamed>"))
