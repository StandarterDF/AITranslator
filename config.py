PROVIDERS = {
    "localllm": {
        "api_key": "sk-LocalHost",
        "base_url": "http://192.168.0.124:8080/v1",
        "model": "QwenCoder",
        "prefill": "<|channel|>thought\n <|channel|>"
    },
}

DEFAULT_PROVIDER = "localllm"
