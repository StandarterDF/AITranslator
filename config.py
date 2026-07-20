import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, dict] = {
    "localllm": {
        "api_key": os.getenv("LOCALLLM_API_KEY", "sk-LocalHost"),
        "base_url": os.getenv("LOCALLLM_BASE_URL", "http://192.168.0.124:8080/v1"),
        "model": os.getenv("LOCALLLM_MODEL", "QwenCoder"),
        "prefill": os.getenv("LOCALLLM_PREFILL", "<|channel|>thought\nМоя задача — перевести текст с английского на русский языки. Я выдаю ТОЛЬКО перевод, без пояснений и оригинального текста. Сохраняю всю пунктуацию. <|channel|>"),
    },
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "prefill": os.getenv("DEEPSEEK_PREFILL", ""),
    },
}

DEFAULT_PROVIDER = "localllm"

TRANSLATION_CHAIN: list[dict] = [
    {"type": "llm", "provider": "localllm", "multiplier": 8, "cap": 16384},
    {"type": "llm", "provider": "localllm", "mode": "completions", "temperature": 0.3, "multiplier": 10, "cap": 32768},
]

LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "https://libretranslate.com/translate")
LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "")

LOG_TRANSLATION_CONTENT = os.getenv("LOG_TRANSLATION_CONTENT", "false").lower() == "true"

PRESETS: dict[str, dict] = {
    "default": {
        "name": "Default (Local LLM)",
        "description": "Local Qwen model via chat then completions fallback",
        "default_provider": "localllm",
        "translation_chain": [
            {"type": "llm", "provider": "localllm", "multiplier": 8, "cap": 16384},
            {"type": "llm", "provider": "localllm", "mode": "completions", "temperature": 0.3, "multiplier": 10, "cap": 32768},
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "description": "DeepSeek API for translation with Google/LibreTranslate fallback",
        "default_provider": "deepseek",
        "translation_chain": [
            {"type": "llm", "provider": "deepseek", "max_tokens": None},
            {"type": "google"}
        ],
    },
}


def list_presets() -> list[dict]:
    return [
        {"key": key, "name": p.get("name", key), "description": p.get("description", "")}
        for key, p in PRESETS.items()
    ]


def load_preset(name: str) -> dict | None:
    if name not in PRESETS:
        logger.error("Preset '%s' not found. Available: %s", name, list(PRESETS.keys()))
        return None
    return dict(PRESETS[name])


def choose_preset_interactive() -> str:
    presets = list_presets()
    if not presets:
        return "default"

    print("\nAvailable presets:")
    for i, p in enumerate(presets, 1):
        desc = p["description"]
        print(f"  {i}. {p['name']}" + (f" — {desc}" if desc else ""))

    while True:
        try:
            choice = input(f"\nSelect preset [1-{len(presets)}] (default 1): ").strip()
            if not choice:
                choice = "1"
            idx = int(choice) - 1
            if 0 <= idx < len(presets):
                print(f"Selected: {presets[idx]['name']}\n")
                return presets[idx]["key"]
            print(f"Please enter a number between 1 and {len(presets)}")
        except (ValueError, EOFError, KeyboardInterrupt):
            print()
            return presets[0]["key"] if presets else "default"


def apply_preset(preset: dict):
    global PROVIDERS, DEFAULT_PROVIDER, TRANSLATION_CHAIN
    global LIBRETRANSLATE_URL, LIBRETRANSLATE_API_KEY, LOG_TRANSLATION_CONTENT

    if "providers" in preset:
        for name, cfg in preset["providers"].items():
            if name in PROVIDERS:
                PROVIDERS[name].update(cfg)
            else:
                PROVIDERS[name] = cfg
        logger.debug("Applied %d providers from preset", len(preset["providers"]))

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
        LOG_TRANSLATION_CONTENT = str(val).lower() in ("true", "1", "yes") if not isinstance(val, bool) else val
