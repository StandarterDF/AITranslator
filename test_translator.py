import pytest
from unittest.mock import patch, MagicMock

from validator import validate_translation, LANGUAGE_SCRIPTS
from cache_manager import _cache_key


class TestValidateTranslation:
    def test_russian_cyrillic_passes(self):
        text = "Привет, как дела? Это тестовый перевод."
        assert validate_translation(text, "ru") is True

    def test_russian_numeric_only_passes(self):
        text = "12345"
        assert validate_translation(text, "ru") is True

    def test_russian_english_only_fails(self):
        text = "Hello, how are you? This is a test."
        assert validate_translation(text, "ru") is False

    def test_russian_mixed_mostly_english_fails(self):
        text = "Hello, how are you? Today is a beautiful sunny morning in California and I love it so much."
        assert validate_translation(text, "ru") is False

    def test_russian_custom_threshold(self):
        text = "Hello это тест hello hello hello"
        assert validate_translation(text, "ru", 0.2) is True
        assert validate_translation(text, "ru", 0.3) is False

    def test_english_target_accepts_latin(self):
        assert validate_translation("Hello world, this is English.", "en") is True

    def test_empty_text_passes(self):
        assert validate_translation("", "ru") is True

    def test_no_alpha_chars_passes(self):
        assert validate_translation("--- 123 !!!", "ru") is True

    def test_ukrainian_cyrillic_passes(self):
        assert validate_translation("Привіт, як справи?", "uk") is True

    def test_korean_hangul_passes(self):
        assert validate_translation("안녕하세요, 어떻게 지내세요?", "ko") is True

    def test_unknown_language_passes(self):
        assert validate_translation("whatever text", "unknown_lang") is True

    def test_latin_languages_in_scripts(self):
        latin_langs = ["en", "es", "fr", "de", "it", "pt", "nl", "pl", "tr",
                       "vi", "cs", "sv", "da", "fi", "id", "ms", "no", "ro", "hu"]
        for lang in latin_langs:
            assert lang in LANGUAGE_SCRIPTS, f"Missing script for {lang}"
            assert validate_translation("Hello world test text.", lang) is True

    def test_japanese_accepts_cjk_and_kana(self):
        assert validate_translation("こんにちは、お元気ですか？", "ja") is True

    def test_chinese_accepts_cjk(self):
        assert validate_translation("你好，你好吗？", "zh") is True

    def test_arabic_passes(self):
        assert validate_translation("مرحبا كيف حالك", "ar") is True

    def test_hebrew_passes(self):
        assert validate_translation("שלום איך אתה", "he") is True

    def test_greek_passes(self):
        assert validate_translation("Γεια σου, πως είσαι;", "el") is True

    def test_thai_passes(self):
        assert validate_translation("สวัสดีครับ สบายดีไหม", "th") is True

    def test_hindi_devanagari_passes(self):
        assert validate_translation("नमस्ते, आप कैसे हैं?", "hi") is True


class TestCacheKey:
    def test_cache_key_deterministic(self):
        k1 = _cache_key("en", "ru", "Hello")
        k2 = _cache_key("en", "ru", "Hello")
        assert k1 == k2

    def test_cache_key_different_source(self):
        k1 = _cache_key("en", "ru", "Hello")
        k2 = _cache_key("es", "ru", "Hello")
        assert k1 != k2

    def test_cache_key_different_text(self):
        k1 = _cache_key("en", "ru", "Hello")
        k2 = _cache_key("en", "ru", "World")
        assert k1 != k2

    def test_cache_key_is_sha256_hex(self):
        k = _cache_key("en", "ru", "test")
        assert len(k) == 64
        assert all(c in "0123456789abcdef" for c in k)


class TestFormatPrompt:
    def test_format_prompt_uses_language_names(self):
        from prompt_template import format_prompt
        result = format_prompt("en", "ru", "Hello world")
        assert "English" in result["system"]
        assert "Russian" in result["system"]
        assert "English" in result["user"]
        assert "Russian" in result["user"]
        assert "Hello world" in result["user"]

    def test_format_prompt_fallback_for_unknown_lang(self):
        from prompt_template import format_prompt
        result = format_prompt("xx", "ru", "test")
        assert "xx" in result["system"]
        assert "xx" in result["user"]

    def test_format_prompt_russian_rules_added(self):
        from prompt_template import format_prompt
        result_ru = format_prompt("en", "ru", "test")
        result_fr = format_prompt("en", "fr", "test")
        assert "формальное «Вы»" in result_ru["system"]
        assert "формальное «Вы»" not in result_fr["system"]


class TestRestoreUrls:
    def test_no_urls_returns_translation_unchanged(self):
        from translator import restore_urls
        assert restore_urls("Hello", "Привет") == "Привет"

    def test_matching_urls_unchanged(self):
        from translator import restore_urls
        original = "Check https://example.com"
        translation = "Смотри https://example.com"
        assert restore_urls(original, translation) == translation

    def test_missing_url_in_translation_kept(self):
        from translator import restore_urls
        original = "https://example.com test"
        translation = "тест"
        assert restore_urls(original, translation) == "тест"

    def test_urls_missing_in_original_kept(self):
        from translator import restore_urls
        original = "no urls"
        translation = "https://example.com text"
        assert restore_urls(original, translation) == translation

    def test_restore_reordered_urls(self):
        from translator import restore_urls
        original = "First https://a.com then https://b.com"
        translation = "Сначала https://b.com потом https://a.com"
        result = restore_urls(original, translation)
        assert result.count("https://a.com") == 1
        assert result.count("https://b.com") == 1
        assert result == "Сначала https://a.com потом https://b.com"

    def test_restore_corrupted_urls(self):
        from translator import restore_urls
        original = "Visit https://example.com/page"
        translation = "Посети https://broken-url/page"
        result = restore_urls(original, translation)
        assert "https://example.com/page" in result
        assert "https://broken-url/page" not in result


class TestEstimateTokens:
    def test_minimum_one_token(self):
        from translator import estimate_tokens
        assert estimate_tokens("a") == 1

    def test_typical_length(self):
        from translator import estimate_tokens
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("hello world, this is a test.") == 7

    def test_max_tokens_clamped(self):
        from translator import estimate_max_output_tokens
        assert estimate_max_output_tokens("a", multiplier=1.0, cap=4096) == 256
        result = estimate_max_output_tokens("a" * 1000, multiplier=0.5, cap=100)
        assert result == 256  # clamped to minimum 256
