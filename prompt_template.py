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

LANGUAGE_INSTRUCTIONS = {
    "ru": (
        "IMPORTANT Russian language rules:\n"
        "- Use formal \"Вы\" unless context clearly indicates informal setting\n"
        "- Use correct grammatical cases, genders, and verb conjugations\n"
        "- Translate naturally — adapt idioms and phrasing to sound native in Russian\n"
        "- Use proper punctuation according to Russian rules (em-dash —, quotes «», etc.)\n"
        "- Pay attention to singular/plural and formal/informal distinctions"
    ),
}

SYSTEM_PROMPT = """You are an exact translation engine.

Translate the provided text from the source language to the target language.
Output ONLY the translation — no explanations, no greetings, no notes, no extra text.
Do NOT repeat or echo the input text. Do NOT output both the original text and the translation — output ONLY the translation, nothing else. Your output must be entirely in the target language.
Preserve ALL original punctuation, line breaks, and formatting exactly as in the input (periods, commas, quotes, dashes, exclamation marks, question marks, etc.)."""

USER_TEMPLATE = """Source language: {source}
Target language: {target}

{language_instructions}Text to translate:
{text}

Translation:"""


def format_prompt(source: str, target: str, text: str) -> dict:
    source_name = LANGUAGE_NAMES.get(source, source) if source != "auto" else "Auto-detected language"
    target_name = LANGUAGE_NAMES.get(target, target)
    lang_instructions = LANGUAGE_INSTRUCTIONS.get(target, "")
    if lang_instructions:
        lang_instructions += "\n\n"
    return {
        "system": SYSTEM_PROMPT,
        "user": USER_TEMPLATE.format(
            source=source_name,
            target=target_name,
            language_instructions=lang_instructions,
            text=text,
        ),
    }
