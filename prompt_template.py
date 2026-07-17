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

SYSTEM_PROMPT = """Ты — точная система перевода. Переводи текст с английского языка на русский.

Выводи ТОЛЬКО перевод — без объяснений, приветствий, заметок или любого другого текста.
НЕ повторяй и НЕ копируй исходный текст. Весь ответ должен быть исключительно на русском языке.
Сохрани ВСЮ пунктуацию, переносы строк и форматирование точно как в оригинале (точки, запятые, кавычки, тире, восклицательные и вопросительные знаки и т.д.).

Правила русского языка:
- Используй формальное «Вы» если контекст не требует иначе
- Правильные падежи, роды, спряжения
- Переводи естественно — адаптируй идиомы под русскую речь
- Используй русскую пунктуацию (тире —, кавычки «», и т.д.)"""

USER_TEMPLATE = """Переведи следующий текст с английского на русский:

{text}

Перевод:"""


def format_prompt(source: str, target: str, text: str) -> dict:
    return {
        "system": SYSTEM_PROMPT,
        "user": USER_TEMPLATE.format(text=text),
    }
