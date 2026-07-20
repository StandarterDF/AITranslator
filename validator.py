import re

CYRILLIC = re.compile(r"[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F]")
CJK = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF]")
HIRAGANA = re.compile(r"[\u3040-\u309F]")
KATAKANA = re.compile(r"[\u30A0-\u30FF]")
ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
HEBREW = re.compile(r"[\u0590-\u05FF]")
THAI = re.compile(r"[\u0E00-\u0E7F]")
GREEK = re.compile(r"[\u0370-\u03FF\u1F00-\u1FFF]")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
HANGUL = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")
LATIN = re.compile(r"[a-zA-Z\u00C0-\u024F\u1E00-\u1EFF\u2C00-\u2C5F\uA720-\uA7FF]")

LANGUAGE_SCRIPTS: dict[str, tuple[re.Pattern, ...]] = {
    "ru": (CYRILLIC,),
    "uk": (CYRILLIC,),
    "be": (CYRILLIC,),
    "bg": (CYRILLIC,),
    "sr": (CYRILLIC,),
    "zh": (CJK,),
    "ja": (CJK, HIRAGANA, KATAKANA),
    "ko": (HANGUL,),
    "ar": (ARABIC,),
    "he": (HEBREW,),
    "th": (THAI,),
    "el": (GREEK,),
    "hi": (DEVANAGARI,),
    "en": (LATIN,),
    "es": (LATIN,),
    "fr": (LATIN,),
    "de": (LATIN,),
    "it": (LATIN,),
    "pt": (LATIN,),
    "nl": (LATIN,),
    "pl": (LATIN,),
    "tr": (LATIN,),
    "vi": (LATIN,),
    "cs": (LATIN,),
    "sv": (LATIN,),
    "da": (LATIN,),
    "fi": (LATIN,),
    "id": (LATIN,),
    "ms": (LATIN,),
    "no": (LATIN,),
    "ro": (LATIN,),
    "hu": (LATIN,),
}


def validate_translation(text: str, target_lang: str, threshold: float = 0.5) -> bool:
    patterns = LANGUAGE_SCRIPTS.get(target_lang)
    if patterns is None:
        return True

    total = 0
    matching = 0
    for c in text:
        if c.isalpha():
            total += 1
            if any(p.match(c) for p in patterns):
                matching += 1

    if total == 0:
        return True

    return (matching / total) >= threshold
