import pytest
from unittest.mock import patch, MagicMock

import markdown_guard
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
        latin_langs = [
            "en",
            "es",
            "fr",
            "de",
            "it",
            "pt",
            "nl",
            "pl",
            "tr",
            "vi",
            "cs",
            "sv",
            "da",
            "fi",
            "id",
            "ms",
            "no",
            "ro",
            "hu",
        ]
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

    def test_cache_key_normalizes_line_endings(self):
        k1 = _cache_key("auto", "ru", "Line1\nLine2")
        k2 = _cache_key("auto", "ru", "Line1\r\nLine2")
        k3 = _cache_key("auto", "ru", "Line1\rLine2")
        assert k1 == k2 == k3

    def test_cache_key_normalizes_source(self):
        k_auto = _cache_key("auto", "ru", "Hello")
        k_empty = _cache_key("", "ru", "Hello")
        k_upper = _cache_key("AUTO", "ru", "Hello")
        k_en = _cache_key("en", "ru", "Hello")
        assert k_auto == k_empty == k_upper
        assert k_auto != k_en

    def test_cache_key_normalizes_case_and_whitespace(self):
        k1 = _cache_key("auto", "ru", "Hello")
        k2 = _cache_key("auto", "RU", "  Hello  ")
        assert k1 == k2


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


class TestMarkdownGuard:
    ROUNDTRIP_CASES = [
        "no markdown here",
        "*action* plain",
        "word *word* word",
        "*a* *b* *c*",
        "**bold** and `code`",
        "<!-- comment -->\n\ntext *x*",
        "text with https://example.com/page and *em*",
        '<audio controls=""><source src="https://a.b/c"></audio>',
        "*multi\nline\naction*",
        "**unbalanced * stars**",
    ]

    def test_roundtrip_is_exact(self):
        for text in self.ROUNDTRIP_CASES:
            masked = markdown_guard.mask_markdown(text)
            assert markdown_guard.restore_markdown(masked.text, masked) == text

    def test_has_markdown(self):
        assert markdown_guard.has_markdown("*a*")
        assert markdown_guard.has_markdown("`code`")
        assert markdown_guard.has_markdown("<!-- x -->")
        assert markdown_guard.has_markdown("https://example.com")
        assert not markdown_guard.has_markdown("plain text 123")

    def test_without_fenced_blocks_strips_code(self):
        text = "Hello\n```python\nprint('x')\n```\nDone"
        assert markdown_guard.without_fenced_blocks(text) == "Hello\n\nDone"

    def test_without_fenced_blocks_keeps_plain_text(self):
        text = "Просто текст без кода."
        assert markdown_guard.without_fenced_blocks(text) == text

    def test_without_fenced_blocks_keeps_inline_code(self):
        text = "Use `x` here."
        assert markdown_guard.without_fenced_blocks(text) == text

    def test_placeholder_separated_from_neighbours(self):
        masked = markdown_guard.mask_markdown("x*a*y")
        assert f"x {masked.placeholder(0)} a" in masked.text
        assert f"a {masked.placeholder(1)} y" in masked.text

    def test_missing_placeholders_detected(self):
        masked = markdown_guard.mask_markdown("*a* *b*")
        broken = masked.text.replace(masked.placeholder(0), "")
        assert markdown_guard.missing_placeholders(broken, masked) == [0]

    def test_no_missing_when_intact(self):
        masked = markdown_guard.mask_markdown("*a* *b*")
        assert markdown_guard.missing_placeholders(masked.text, masked) == []

    def test_residual_placeholders_stripped(self):
        masked = markdown_guard.mask_markdown("*a*")
        out = markdown_guard.restore_markdown(
            f"перевод {masked.placeholder(999)} тут", masked
        )
        assert masked.open not in out and masked.close not in out

    def test_collision_guard_picks_other_format(self):
        masked = markdown_guard.mask_markdown("text {{0}} and *em*")
        assert masked.open != "{{"
        assert (
            markdown_guard.restore_markdown(masked.text, masked)
            == "text {{0}} and *em*"
        )

    def test_instruction_mentions_placeholder(self):
        masked = markdown_guard.mask_markdown("*a*")
        assert masked.placeholder(0) in markdown_guard.markdown_instruction(masked)

    def test_emphasis_preserved_through_mask(self):
        masked = markdown_guard.mask_markdown("*Она ушла.*")
        assert masked.text.count(masked.placeholder(0)) == 1
        restored = markdown_guard.restore_markdown(masked.text, masked)
        assert restored == "*Она ушла.*"


class TestMarkdownGuardFenced:
    TRANSLATE_CASES = [
        "```\nHello world\n```",
        "Before ```python\nprint('hi')\n``` after",
        "```\nline one\nline two\n```",
        "```python\n```",
        "````js\ntext\ntext2\n````",
    ]

    def test_roundtrip_is_exact(self):
        for text in self.TRANSLATE_CASES:
            masked = markdown_guard.mask_markdown(text, translate_fenced=True)
            assert markdown_guard.restore_markdown(masked.text, masked) == text

    def test_content_visible_but_fences_masked(self):
        text = "```\nHello world\n```"
        masked = markdown_guard.mask_markdown(text, translate_fenced=True)
        assert "Hello world" in masked.text
        assert "```" not in masked.text
        assert masked.tokens == ["```", "```"]

    def test_lang_tag_kept_separately(self):
        text = "```python\nx = 1\n```"
        masked = markdown_guard.mask_markdown(text, translate_fenced=True)
        assert "```python" in masked.tokens
        assert "x = 1" in masked.text

    def test_default_off_masks_whole_block(self):
        text = "```\nHello world\n```"
        masked = markdown_guard.mask_markdown(text)
        assert "Hello world" not in masked.text
        assert len(masked.tokens) == 1

    def test_inline_code_inside_fence_still_masked(self):
        text = "```\n`inline` and *em*\n```"
        masked = markdown_guard.mask_markdown(text, translate_fenced=True)
        assert "`inline`" not in masked.text
        assert "*em*" not in masked.text

    def test_missing_placeholders_detected(self):
        masked = markdown_guard.mask_markdown(
            "a ```\ncontent\n``` b", translate_fenced=True
        )
        broken = masked.text.replace(masked.placeholder(0), "")
        assert 0 in markdown_guard.missing_placeholders(broken, masked)

    def test_instruction_mentions_fenced_content(self):
        masked = markdown_guard.mask_markdown(
            "```\ncontent\n```", translate_fenced=True
        )
        instr = markdown_guard.markdown_instruction(masked, translate_fenced=True)
        assert masked.placeholder(0) in instr
        assert "блоки кода" in instr

    def test_instruction_plain_when_off(self):
        masked = markdown_guard.mask_markdown("```\ncontent\n```")
        instr = markdown_guard.markdown_instruction(masked)
        assert "блоки кода" not in instr
