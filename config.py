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


def _resolve_api_key(value: str) -> str:
    """Resolve api_key: if value is a non-empty string that exists as an env var,
    substitute os.environ[value]; otherwise keep the literal (e.g. 'sk-LocalHost').
    """
    if value and value in os.environ:
        logger.debug("Resolved api_key '%s' -> env var value", value)
        return os.environ[value]
    return value


def _parse_log_translation_content(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return False


# ---------------------------------------------------------------------------
# Config file resolution
# ---------------------------------------------------------------------------


def _resolve_config_path() -> Path | None:
    """Resolve config file path:
    1. TRANSLATOR_CONFIG env var (absolute or relative to project root)
    2. config.json in project root
    3. config.json.example fallback with warning
    Returns None if nothing found.
    """
    env_path = os.environ.get("TRANSLATOR_CONFIG")
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = Path(__file__).parent / p
        if p.exists():
            return p
        logger.error("Config file from TRANSLATOR_CONFIG not found: %s", p)
        return None

    root_config = Path(__file__).parent / "config.json"
    if root_config.exists():
        return root_config

    example = Path(__file__).parent / "config.json.example"
    if example.exists():
        logger.warning(
            "config.json не найден, использую шаблон %s — скопируй его в config.json",
            example,
        )
        return example

    logger.error(
        "Не найден ни config.json, ни config.json.example. "
        "Создай config.json (или скопируй config.json.example)."
    )
    return None


# ---------------------------------------------------------------------------
# Load and apply config
# ---------------------------------------------------------------------------

config_path = _resolve_config_path()

if config_path is not None:
    try:
        raw = json.loads(config_path.read_text("utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("Failed to parse %s: %s", config_path, e)
        if config_path.name == "config.json":
            example = Path(__file__).parent / "config.json.example"
            if example.exists():
                logger.warning("Falling back to %s", example)
                config_path = example
                try:
                    raw = json.loads(config_path.read_text("utf-8"))
                except (OSError, ValueError) as e2:
                    logger.error("Fallback also failed: %s", e2)
                    raw = {}
            else:
                raw = {}
        else:
            raw = {}
    else:
        if not isinstance(raw, dict):
            logger.warning(
                "%s root is not a JSON object — using empty config", config_path
            )
            raw = {}
else:
    raw = {}

# --- Apply to module globals ---

PROVIDERS: dict[str, dict] = {}
if "providers" in raw and isinstance(raw["providers"], dict):
    for name, cfg in raw["providers"].items():
        if not isinstance(cfg, dict):
            continue
        provider_cfg = {}
        for key, val in cfg.items():
            if key == "api_key":
                provider_cfg["api_key"] = (
                    _resolve_api_key(val) if isinstance(val, str) else val
                )
            elif key == "reasoning_effort":
                provider_cfg["reasoning_effort"] = (
                    _parse_reasoning_effort(val) if isinstance(val, str) else val
                )
            else:
                provider_cfg[key] = val
        PROVIDERS[name] = provider_cfg

# DEFAULT_PROVIDER: from json, or None if absent
DEFAULT_PROVIDER: str | None = (
    raw.get("default_provider") if "default_provider" in raw else None
)

# TRANSLATION_CHAIN: from json, default []
TRANSLATION_CHAIN: list[dict] = (
    raw.get("translation_chain", []) if "translation_chain" in raw else []
)

# LibreTranslate
LIBRETRANSLATE_URL: str = raw.get(
    "libretranslate_url", "https://libretranslate.com/translate"
)
LIBRETRANSLATE_API_KEY: str = raw.get("libretranslate_api_key", "")

# Logging toggle
LOG_TRANSLATION_CONTENT: bool = _parse_log_translation_content(
    raw.get("log_translation_content", False)
)


def _parse_log_level(value) -> str:
    """Parse log_level value. Returns uppercase string or 'INFO' on invalid input."""
    valid = ("DEBUG", "INFO", "WARNING", "ERROR")
    if isinstance(value, str) and value.upper() in valid:
        return value.upper()
    logger.warning("Невалидное значение log_level=%r, используется 'INFO'", value)
    return "INFO"


LOG_LEVEL: str = _parse_log_level(raw.get("log_level", "INFO"))

logger.debug(
    "Loaded config from %s: providers=%s default=%s chain=%s",
    config_path,
    list(PROVIDERS.keys()),
    DEFAULT_PROVIDER,
    len(TRANSLATION_CHAIN),
)


# ---------------------------------------------------------------------------
# Reasoning state (runtime F2 override)
# ---------------------------------------------------------------------------


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
