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
}


def validate_translation(text: str, target_lang: str, threshold: float = 0.5) -> bool:
    patterns = LANGUAGE_SCRIPTS.get(target_lang)
    if patterns is None:
        return True

    total = sum(1 for c in text if c.isalpha())
    if total == 0:
        return True

    matching = sum(1 for c in text if any(p.match(c) for p in patterns))
    return (matching / total) >= threshold
