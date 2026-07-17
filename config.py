PROVIDERS = {
    "localllm": {
        "api_key": "sk-LocalHost",
        "base_url": "http://192.168.0.124:8080/v1",
        "model": "QwenCoder",
        "prefill": "<|channel|>thought\nМоя задача — перевести текст с английского на русский языки. Я выдаю ТОЛЬКО перевод, без пояснений и оригинального текста. Сохраняю всю пунктуацию. <|channel|>"
    },
}

DEFAULT_PROVIDER = "localllm"

TRANSLATION_CHAIN = [
    {"type": "llm", "provider": "localllm", "multiplier": 8, "cap": 16384},
    {"type": "llm", "provider": "localllm", "prefill": None, "temperature": 0.3, "multiplier": 10, "cap": 32768},
]

LIBRETRANSLATE_URL = "https://libretranslate.com/translate"
LIBRETRANSLATE_API_KEY = ""

LOG_TRANSLATION_CONTENT = False
