LANGUAGE_NAMES = {
    "auto": "Auto-detected language",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "cs": "Czech",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "el": "Greek",
    "he": "Hebrew",
    "id": "Indonesian",
    "ms": "Malay",
    "no": "Norwegian",
    "ro": "Romanian",
    "uk": "Ukrainian",
    "hu": "Hungarian",
}

_SYSTEM_PROMPT_BASE = """Ты — точная система перевода. Переводи текст с {source_name} языка на {target_name}.

Выводи ТОЛЬКО перевод — без объяснений, приветствий, заметок или любого другого текста.
НЕ повторяй и НЕ копируй исходный текст. Весь ответ должен быть исключительно на {target_name} языке.
Сохрани ВСЮ пунктуацию, переносы строк и форматирование точно как в оригинале (точки, запятые, кавычки, тире, восклицательные и вопросительные знаки и т.д.)."""

_RUSSIAN_RULES = """
Правила русского языка:
- Используй формальное «Вы» если контекст не требует иначе
- Правильные падежи, роды, спряжения
- Переводи естественно — адаптируй идиомы под русскую речь
- Используй русскую пунктуацию (тире —, кавычки «», и т.д.)"""

_USER_TEMPLATE = """Переведи следующий текст с {source_name} на {target_name}:

{text}

Перевод:"""


def format_prompt(source: str, target: str, text: str) -> dict:
    source_name = LANGUAGE_NAMES.get(source, source)
    target_name = LANGUAGE_NAMES.get(target, target)

    system = _SYSTEM_PROMPT_BASE.format(source_name=source_name, target_name=target_name)
    if target == "ru":
        system += _RUSSIAN_RULES

    user = _USER_TEMPLATE.format(source_name=source_name, target_name=target_name, text=text)
    return {"system": system, "user": user}
