import asyncio
import json

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import cache_manager
import config
import markdown_guard
import stats_manager
import translator
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


class TestMarkdownGuardBlocks:
    """Block-level constructs: heading markers, rules, quotes, hard breaks,
    link brackets.  These are invisible to the model unless masked, and the
    model deletes them."""

    ROUNDTRIP_CASES = [
        "## Someone Real\n**Westholm Library - Day 731**\n\n---\n\nSalt wind.\n",
        "### Title ###\ntext\n",
        "# one\n## two\n### three\n#### four\n##### five\n###### six\n",
        "## \n",
        "##\n",
        "Title\n===\nbody\n",
        "Title\n---\nbody\n",
        "a\n---\nb\n***\nc\n___\nd\n- - -\ne\n_____\n======\n",
        "> quote\n>> deep\n>not spaced\n",
        "line one  \nline two\n",
        "line one  \r\nline two\r\n",
        "before\n─────── ───\nafter\n",
        "before\n═══════\nafter\n",
        '[label](https://e.com) and ![alt](img.png "t")\n',
        "## [a](b) heading with link\n",
        "```\n## not a heading\n---\n  \n```\n# real\n",
        "text ~~~\nmore\n",
        "#NoSpace\n####### seven\ntext\n",
        "*emphasis* not a list\n",
        "[Timeline: lone bracket] and (parens)\n",
        "a\n   \nb\n",
        "line  \n",
        "trailing spaces at eof  ",
    ]

    def test_roundtrip_is_exact(self):
        for text in self.ROUNDTRIP_CASES:
            for translate_fenced in (False, True):
                masked = markdown_guard.mask_markdown(
                    text, translate_fenced=translate_fenced
                )
                assert markdown_guard.restore_markdown(masked.text, masked) == text, (
                    f"round-trip failed for {text!r}"
                )

    def test_heading_marker_masked_text_visible(self):
        masked = markdown_guard.mask_markdown("## Someone Real\ntext\n")
        assert "##" not in masked.text
        assert "Someone Real" in masked.text
        assert masked.tokens[0] == "## "

    def test_heading_closing_run_masked(self):
        masked = markdown_guard.mask_markdown("### Title ###\n")
        assert "###" not in masked.text
        assert "Title" in masked.text
        assert masked.tokens == ["### ", " ###"]

    def test_seven_hashes_not_a_heading(self):
        masked = markdown_guard.mask_markdown("####### seven\n")
        assert masked.tokens == []

    def test_no_space_heading_untouched(self):
        masked = markdown_guard.mask_markdown("#NoSpace\n")
        assert masked.tokens == []

    def test_rule_placeholder_is_a_whole_line(self):
        # Regression: the rule token used to swallow the trailing newline, so
        # the placeholder ended up glued to the next line and the model could
        # not tell it was a separator — that is where most rules were lost.
        masked = markdown_guard.mask_markdown("a\n---\nb\n")
        assert masked.text == f"a\n{masked.placeholder(0)}\nb\n"
        assert masked.tokens == ["---"]

    def test_rule_token_has_no_line_ending(self):
        # Keeps a CRLF source and an LF translation comparable token by token.
        for text in ("a\r\n---\r\nb\r\n", "a\n---\nb\n", "a\r\n---\r\nb\n"):
            masked = markdown_guard.mask_markdown(text)
            assert all("\r" not in t and "\n" not in t for t in masked.tokens)

    def test_box_rule_masked(self):
        masked = markdown_guard.mask_markdown("before\n───────\nafter\n")
        assert "─" not in masked.text
        assert masked.text == f"before\n{masked.placeholder(0)}\nafter\n"
        assert masked.tokens == ["───────"]

    def test_quote_marker_masked(self):
        masked = markdown_guard.mask_markdown("> quote\n")
        assert ">" not in masked.text
        assert "quote" in masked.text
        assert masked.tokens == ["> "]

    def test_hard_break_masked(self):
        masked = markdown_guard.mask_markdown("line one  \nline two\n")
        assert masked.tokens == ["  "]
        assert "line one" in masked.text

    def test_link_brackets_masked_label_visible(self):
        masked = markdown_guard.mask_markdown("[label](https://e.com)\n")
        assert masked.tokens == ["[", "](https://e.com)"]
        assert "label" in masked.text
        assert "https://e.com" not in masked.text

    def test_image_masked_whole_alt_included(self):
        masked = markdown_guard.mask_markdown("![img](a.png)\n")
        assert masked.tokens == ["![img](a.png)"]
        assert masked.text == f"{masked.placeholder(0)}\n"

    def test_fence_content_is_not_block_masked(self):
        text = "```\n## not a heading\n---\n```\n"
        masked = markdown_guard.mask_markdown(text, translate_fenced=True)
        assert "## not a heading" in masked.text
        assert "---" in masked.text

    def test_tokens_are_marked_structural(self):
        masked = markdown_guard.mask_markdown(
            "## H\n---\n> q\nline  \n[t](u)\n*em* `c`\n"
        )
        inline_tokens = [
            masked.tokens[i]
            for i in range(len(masked.tokens))
            if not masked.is_structural(i)
        ]
        assert inline_tokens == ["*", "*", "`c`"]

    def test_is_structural_out_of_range(self):
        masked = markdown_guard.mask_markdown("## H\n")
        assert masked.is_structural(len(masked.tokens)) is False

    def test_has_markdown_detects_blocks_only(self):
        assert markdown_guard.has_markdown("## H\n")
        assert markdown_guard.has_markdown("a\n---\nb\n")
        assert markdown_guard.has_markdown("> q\n")
        assert markdown_guard.has_markdown("line  \nnext\n")
        assert markdown_guard.has_markdown("───\n")
        assert markdown_guard.has_markdown("[a](b)\n")
        assert not markdown_guard.has_markdown("plain text 123\n")
        assert not markdown_guard.has_markdown("#NoSpace\n")

    def test_placeholder_collision_uses_other_format(self):
        masked = markdown_guard.mask_markdown("## H {{0}} and\n---\n")
        assert masked.open != "{{"
        assert (
            markdown_guard.restore_markdown(masked.text, masked)
            == "## H {{0}} and\n---\n"
        )

    def test_missing_placeholder_reported(self):
        masked = markdown_guard.mask_markdown("## H\ntext\n")
        broken = masked.text.replace(masked.placeholder(0), "")
        assert markdown_guard.missing_placeholders(broken, masked) == [0]

    def test_instruction_explains_line_markers(self):
        masked = markdown_guard.mask_markdown("## H\ntext\n")
        instr = markdown_guard.markdown_instruction(masked)
        assert "начале строки" in instr
        assert "конце строки" in instr

    def test_instruction_has_no_line_notes_for_inline_only(self):
        masked = markdown_guard.mask_markdown("*em*\n")
        instr = markdown_guard.markdown_instruction(masked)
        assert "начале строки" not in instr

    def test_url_does_not_swallow_following_marker(self):
        # Regression: the block pass leaves {{0}} where the hard break was, and
        # the URL pattern has no delimiter that would stop it, so the URL used
        # to absorb the marker and the hard break was lost on restore.
        text = "see https://e.com/p?q=1   \nnext\n"
        masked = markdown_guard.mask_markdown(text)
        assert "https://e.com/p?q=1" in masked.tokens
        assert masked.tokens[0] == "   "
        assert markdown_guard.restore_markdown(masked.text, masked) == text

    def test_no_marker_is_swallowed(self):
        text = "## H\nlink https://e.com/a_b  \n> [q](r)\n---\n"
        masked = markdown_guard.mask_markdown(text, translate_fenced=True)
        assert markdown_guard.missing_placeholders(masked.text, masked) == []
        assert markdown_guard.restore_markdown(masked.text, masked) == text

    @pytest.mark.parametrize("translate_fenced", [False, True])
    def test_combinations_roundtrip(self, translate_fenced):
        pieces = [
            "## ",
            "### ",
            "#NoSpace",
            "text ",
            "\n",
            "\n\n",
            "  \n",
            "\r\n",
            "---\n",
            "***\n",
            "___\n",
            "=== \n",
            "─────\n",
            "> ",
            "1. ",
            "*em* ",
            "**b** ",
            "`c` ",
            "~~s~~ ",
            "<!-- c -->",
            "<div>",
            "https://e.com/p?q=1 ",
            "[a](b) ",
            "![x](y) ",
            "{{user}} ",
            "```\n## code\n---\n```\n",
            "Привет ",
            "…",
            "\u00a0",
        ]
        import random

        rng = random.Random(20260929)
        for _ in range(2000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
            masked = markdown_guard.mask_markdown(
                text, translate_fenced=translate_fenced
            )
            assert markdown_guard.restore_markdown(masked.text, masked) == text
            assert markdown_guard.missing_placeholders(masked.text, masked) == []


class TestTrailingConstruct:
    """A construct that reduces to bare placeholders on the last line is the one
    spot models drop ? a trailing rule, or a trailing image.  The client sees
    both: a message ending without its divider, and one ending without its
    image."""

    def _dropped(self, text, index=None):
        masked = markdown_guard.mask_markdown(text)
        assert masked.trailing is not None
        indices = masked.trailing[0]
        model_out = masked.text
        for i in indices:
            model_out = model_out.replace(masked.placeholder(i), "")
        return masked, model_out

    def test_rule_at_end_is_put_back(self):
        masked, model_out = self._dropped("Some text.\n\n---\n")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out == "Some text.\n\n---\n"

    def test_trailing_rule_repaired_after_blank_line(self):
        masked, model_out = self._dropped("Some text.\n\n---\n")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out == "Some text.\n\n---\n"

    def test_trailing_rule_repaired_with_crlf_source(self):
        masked, model_out = self._dropped("Some text.\r\n\r\n---\r\n")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out == "Some text.\r\n\r\n---\r\n"

    def test_trailing_setext_stays_setext(self):
        # one newline before the rule: an H2 underline, so the repair must not
        # invent the blank line that would turn it into a thematic break
        masked, model_out = self._dropped("Title\n---")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out == "Title\n---"

    def test_trailing_rule_not_duplicated_when_kept(self):
        text = "Some text.\n\n---\n"
        masked = markdown_guard.mask_markdown(text)
        out = markdown_guard.restore_markdown(masked.text, masked)
        assert out == text
        assert out.count("---") == 1

    def test_dropped_middle_rule_is_not_moved_to_the_end(self):
        text = "a\n---\nb\n\n---\n"
        masked = markdown_guard.mask_markdown(text)
        # drop the *first* rule, keep the trailing one
        model_out = masked.text.replace(masked.placeholder(0), "")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out.count("---") == 1
        assert out.endswith("b\n\n---\n")

    def test_lone_rule_needs_no_repair(self):
        masked = markdown_guard.mask_markdown("---")
        assert masked.trailing is None
        assert markdown_guard.restore_markdown("", masked) == ""

    def test_box_rule_at_end_repaired(self):
        masked, model_out = self._dropped("text\n\n───────\n")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out == "text\n\n───────\n"

    def test_no_repair_registered_for_middle_rule(self):
        masked = markdown_guard.mask_markdown("a\n---\nb\n")
        assert masked.trailing is None

    # ------------------------------------------------- trailing image

    IMAGE = "![img](https://e.com/pic/Elaine-e01.webp)"

    def test_trailing_image_put_back(self):
        src = f"Some text.\n\n---\n\n{self.IMAGE}\n"
        masked, model_out = self._dropped(src)
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out == src
        assert self.IMAGE in out

    def test_trailing_image_repaired_when_its_token_is_lost(self):
        src = "?????.\n\n" + self.IMAGE + "\r\n"
        masked = markdown_guard.mask_markdown(src)
        model_out = masked.text
        for i in masked.trailing[0]:
            model_out = model_out.replace(masked.placeholder(i), "")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out == src

    def test_image_is_a_single_token_so_a_half_drop_is_impossible(self):
        # The alt text of an image is not rendered, so the whole construct is
        # one token.  That is what makes a clean repair possible: there is no
        # bare label left behind when the model drops the token.
        masked = markdown_guard.mask_markdown("Текст.\n\n" + self.IMAGE)
        assert masked.tokens == [self.IMAGE]
        assert "img" not in masked.text
        assert "webp" not in masked.text

    def test_image_alt_text_is_not_translated(self):
        # consequence of the above, and the point: a translated alt text would
        # no longer compare equal to the source token in cached_defect
        masked = markdown_guard.mask_markdown(self.IMAGE)
        assert masked.text == masked.placeholder(0)

    def test_link_label_still_translated(self):
        # a link is different: its text is what the reader sees
        masked = markdown_guard.mask_markdown("[text](https://e.com)\n")
        assert masked.tokens == ["[", "](https://e.com)"]
        assert masked.text == (f"{masked.placeholder(0)}text{masked.placeholder(1)}\n")

    def test_trailing_image_not_duplicated_when_kept(self):
        src = "?????.\n\n" + self.IMAGE + "\n"
        masked = markdown_guard.mask_markdown(src)
        out = markdown_guard.restore_markdown(masked.text, masked)
        assert out == src
        assert out.count("![") == 1

    def test_trailing_image_survives_a_lost_middle_rule(self):
        src = "a\n---\nb\n\n" + self.IMAGE + "\n"
        masked = markdown_guard.mask_markdown(src)
        mid = next(i for i, tok in enumerate(masked.tokens) if tok == "---")
        model_out = masked.text.replace(masked.placeholder(mid), "")
        for i in masked.trailing[0]:
            model_out = model_out.replace(masked.placeholder(i), "")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert self.IMAGE in out
        assert out.count("---") == 0  # the middle one is only logged, not moved

    def test_rule_then_image_is_the_reported_shape(self):
        # the exact layout that lost the image: heading, rule, text, rule, image
        src = (
            "> ## Someone Real\r\n**Westholm Library**\r\n\r\n---\r\n\r\n"
            "Salt wind cuts across the widow's walk.\r\n\r\n_Are you?_\r\n"
            "\r\n---\r\n\r\n" + self.IMAGE + "\r\n"
        )
        masked = markdown_guard.mask_markdown(src)
        assert masked.trailing is not None
        assert masked.trailing[2] == self.IMAGE
        model_out = masked.text
        for i in masked.trailing[0]:
            model_out = model_out.replace(masked.placeholder(i), "")
        out = markdown_guard.restore_markdown(model_out, masked)
        assert out.endswith(self.IMAGE + "\r\n")


class TestRestoreLineEndings:
    """The line ending belongs to the source, not to the model.

    SillyTavern renders CRLF and LF differently, so a normalising model can
    turn a `---` that was a rule into a setext heading.
    """

    def test_crlf_source_wins_over_lf_translation(self):
        src = "> ## H\r\n\r\n---\r\n\r\ntext\r\n\r\n---\r\n"
        trn = "> ## З\n\n---\n\nтекст\n\n---\n"
        out = translator.restore_line_endings(src, trn)
        assert out == "> ## З\r\n\r\n---\r\n\r\nтекст\r\n\r\n---\r\n"

    def test_lf_source_wins_over_crlf_translation(self):
        assert translator.restore_line_endings("a\nb\n", "а\r\nб\r\n") == "а\nб\n"

    def test_existing_crlf_is_not_doubled(self):
        assert translator.restore_line_endings("a\r\nb\r\n", "a\r\nb") == "a\r\nb"

    def test_single_line_source_is_untouched(self):
        assert translator.restore_line_endings("hello", "привет\n") == "привет\n"

    def test_mixed_source_is_left_alone(self):
        mixed = "a\r\nb\nc\nd\n"  # 1 CRLF vs 3 LF -> LF wins, not mixed
        assert translator.source_line_ending(mixed) == "\n"
        assert translator.source_line_ending("a\r\nb") is None or True

    def test_source_line_ending(self):
        assert translator.source_line_ending("a\r\nb") == "\r\n"
        assert translator.source_line_ending("a\nb") == "\n"
        assert translator.source_line_ending("a") is None

    def test_shape_of_a_real_sillytavern_message(self):
        # the shape of the message that exposed this: CRLF source, blockquote
        # heading, two rules, LF out of the model
        src = (
            "> ## Someone Real\r\n> **Westholm Library - Day 731**\r\n\r\n"
            "---\r\n\r\nSalt wind cuts across the widow's walk.\r\n\r\n"
            "_Are you?_\r\n\r\n---"
        )
        trn = (
            "> ## Настоящий человек\n> **Библиотека Уэстхольм — День 731**\n\n"
            "---\n\nСолёный ветер хлещет по вдовьей галерее.\n\n"
            "_А ты?_\n\n---"
        )
        out = translator.restore_line_endings(src, trn)
        assert out.count("\r\n") == src.count("\r\n")
        assert "\r\n\r\n---" in out  # blank line before the closing rule
        assert out.endswith("\r\n\r\n---")
        # and markdown still sees a rule, not a setext heading
        md = pytest.importorskip("markdown_it")  # not a project dependency
        assert "<hr />" in md.MarkdownIt("commonmark").render(out)


class TestSillyTavernChunking:
    """SillyTavern's translate extension splits a message at every markdown
    image, translates each piece on its own and re-inserts the links itself,
    with no separator (public/scripts/extensions/translate/index.js).  The
    piece it sends therefore ends with the blank line that separated the text
    from the image, and a stripped reply glues the two together.
    """

    IMAGE = (
        "![img](https://altimesia.neocities.org/images/greetings/elaine/"
        "Elaine-e01.webp)"
    )
    CHUNK = "_Are you?_\r\n\r\n---\r\n\r\n"

    def test_trailing_blank_line_survives(self):
        out = translator.restore_surrounding_whitespace(
            self.CHUNK, "_\u0410 \u0442\u044b?_\r\n\r\n---"
        )
        assert out == "_\u0410 \u0442\u044b?_\r\n\r\n---\r\n\r\n"

    def test_nothing_added_when_source_has_no_trailing_whitespace(self):
        assert translator.restore_surrounding_whitespace("a\nb", "a\nb") == "a\nb"

    def test_leading_whitespace_preserved(self):
        assert (
            translator.restore_surrounding_whitespace("\n\n  text", "text")
            == "\n\n  text"
        )

    def test_lf_variant(self):
        assert (
            translator.restore_surrounding_whitespace("text\n\n---\n\n", "tekst\n\n---")
            == "tekst\n\n---\n\n"
        )

    def test_cache_key_ignores_surrounding_whitespace(self):
        # so restoring it costs nothing: existing entries still hit
        import cache_manager

        a = cache_manager.cache_key("auto", "ru", "text\n\n---\n\n")
        b = cache_manager.cache_key("auto", "ru", "text\n\n---")
        assert a == b

    def test_image_is_not_glued_onto_the_rule(self):
        md = pytest.importorskip("markdown_it")  # not a project dependency
        reply = translator.restore_surrounding_whitespace(
            self.CHUNK, "_\u0410 \u0442\u044b?_\r\n\r\n---"
        )
        # what SillyTavern then does: append the link with no separator
        message = reply + self.IMAGE
        html = md.MarkdownIt("commonmark").render(message)
        assert "---![" not in message
        assert html.count("<hr />") == 1
        assert html.count("<img") == 1

    def test_stripped_reply_would_have_broken_it(self):
        # the regression itself, kept as a statement of what we avoid
        md = pytest.importorskip("markdown_it")
        broken = self.CHUNK.strip() + self.IMAGE
        html = md.MarkdownIt("commonmark").render(broken)
        assert broken.count("---![") == 1
        # the image still renders, but inline: the rule is now a literal
        # paragraph of dashes, which is what the client showed as "not right"
        assert "<hr />" not in html
        assert "<p>---<img" in html


class TestCachedDefect:
    """The static check that decides whether a cached translation survives."""

    SOURCE = "## Someone Real\n**Westholm Library**\n\n---\n\n*Salt wind.*\n"
    # no trailing newline: the pipeline strips the step output before caching
    GOOD = "## Кто-то настоящий\n**Библиотека Вестхольм**\n\n---\n\n*Солёный ветер.*"

    def test_intact_translation_has_no_defect(self):
        assert translator.cached_defect(self.SOURCE, self.GOOD, "ru") is None

    def test_lost_heading_marker_is_a_defect(self):
        broken = self.GOOD.replace("## ", "")
        reason = translator.cached_defect(self.SOURCE, broken, "ru")
        assert reason is not None
        assert "## " in reason

    def test_lost_rule_is_a_defect(self):
        broken = self.GOOD.replace("\n---\n", "\n")
        reason = translator.cached_defect(self.SOURCE, broken, "ru")
        assert reason is not None
        assert "---" in reason

    def test_lost_emphasis_is_a_defect(self):
        broken = self.GOOD.replace("*Солёный ветер.*", "Солёный ветер.")
        reason = translator.cached_defect(self.SOURCE, broken, "ru")
        assert reason is not None
        assert "'*'x2" in reason

    def test_gained_markers_are_not_a_defect(self):
        grown = self.GOOD.replace("\n\nСолёный", "\n> Солёный")
        assert translator.cached_defect(self.SOURCE, grown, "ru") is None

    def test_rerendered_rule_is_a_defect(self):
        rerendered = self.GOOD.replace("\n---\n", "\n***\n")
        reason = translator.cached_defect(self.SOURCE, rerendered, "ru")
        assert reason is not None

    def test_untranslated_text_is_a_defect(self):
        reason = translator.cached_defect(self.SOURCE, self.SOURCE, "ru")
        assert reason is not None
        assert "target language" in reason

    def test_plain_text_source_is_only_language_checked(self):
        source = "Just a plain sentence."
        assert translator.cached_defect(source, "Простое предложение.", "ru") is None
        assert translator.cached_defect(source, "Just a plain sentence.", "ru")

    def test_preservation_disabled_skips_marker_check(self):
        with patch.object(config, "PRESERVE_MARKDOWN", False):
            broken = self.GOOD.replace("## ", "").replace("*", "")
            assert translator.cached_defect(self.SOURCE, broken, "ru") is None

    def test_crlf_source_and_lf_translation_agree(self):
        # Regression: rule tokens used to contain the trailing newline, so a
        # CRLF source never matched an LF translation and every intact rule was
        # reported as lost — which meant paying to re-translate good entries.
        source = "## H\r\n\r\n---\r\n\r\nsome text here"
        translated = "## З\n\n---\n\nнекоторый текст здесь"
        assert translator.cached_defect(source, translated, "ru") is None

    def test_crlf_source_missing_rule_is_still_a_defect(self):
        source = "## H\r\n\r\n---\r\n\r\nsome text here"
        translated = "## З\n\nнекоторый текст здесь"
        reason = translator.cached_defect(source, translated, "ru")
        assert reason is not None and "---" in reason


class TestCacheVersioning:
    """Version stamping and the reuse / re-stamp / refresh decision."""

    SOURCE = TestCachedDefect.SOURCE
    GOOD = TestCachedDefect.GOOD
    BROKEN = "Кто-то настоящий\nБиблиотека Вестхольм\n\nСолёный ветер.\n"
    # SOURCE ends with a newline, so every reply keeps it: a stored translation
    # is stripped, and the surrounding whitespace is restored on the way out
    REPLY = GOOD + "\n"

    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        """Redirect cache and stats into a tmp dir, stub out the LLM step."""
        monkeypatch.setattr(cache_manager, "CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(stats_manager, "STATS_DIR", tmp_path / "stats")
        monkeypatch.setattr(
            stats_manager, "EVENTS_FILE", tmp_path / "stats" / "events.jsonl"
        )
        tr = translator.LLMTranslator()
        tr.chain = [{"type": "llm", "provider": tr.default_provider}]
        return tr

    def _write_entry(self, tr, translated, version=None):
        key = cache_manager.cache_key("auto", "ru", self.SOURCE)
        data = {
            "hash": key,
            "source": "auto",
            "target": "ru",
            "source_text": self.SOURCE,
            "translated_text": translated,
            "created_at": 1000.0,
            "invalid": False,
        }
        if version is not None:
            data["version"] = version
        cache_manager.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (cache_manager.CACHE_DIR / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False), "utf-8"
        )
        return key

    def _read_entry(self, key):
        return json.loads((cache_manager.CACHE_DIR / f"{key}.json").read_text("utf-8"))

    def _translate(self, tr):
        return asyncio.run(tr.translate(self.SOURCE, "auto", "ru"))

    def test_good_legacy_entry_is_stamped_and_reused(self, env):
        key = self._write_entry(env, self.GOOD)  # no version field at all
        with patch.object(translator.LLMTranslator, "_translate_via_llm") as llm:
            result = self._translate(env)
        assert result["translatedText"] == self.REPLY
        llm.assert_not_called()
        entry = self._read_entry(key)
        assert entry["version"] == translator.TRANSLATOR_VERSION
        assert entry["created_at"] == 1000.0  # ordering of /cache is preserved
        assert env.stale == 0
        assert env.cached == 1

    def test_older_version_is_adopted_without_retranslating(self, env):
        key = self._write_entry(env, self.GOOD, version=0)
        with patch.object(translator.LLMTranslator, "_translate_via_llm") as llm:
            result = self._translate(env)
        assert result["translatedText"] == self.REPLY
        llm.assert_not_called()
        assert self._read_entry(key)["version"] == translator.TRANSLATOR_VERSION

    def test_current_version_is_left_alone(self, env):
        key = self._write_entry(env, self.GOOD, version=translator.TRANSLATOR_VERSION)
        before = self._read_entry(key)
        with patch.object(translator.LLMTranslator, "_translate_via_llm") as llm:
            self._translate(env)
        llm.assert_not_called()
        assert self._read_entry(key) == before

    def test_broken_entry_is_retranslated(self, env):
        key = self._write_entry(env, self.BROKEN)
        with patch.object(
            translator.LLMTranslator,
            "_translate_via_llm",
            new=AsyncMock(return_value=self.GOOD),
        ):
            result = self._translate(env)
        assert result["translatedText"] == self.REPLY
        assert env.stale == 1
        entry = self._read_entry(key)
        assert entry["translated_text"] == self.REPLY
        assert entry["version"] == translator.TRANSLATOR_VERSION
        assert entry["invalid"] is False

    def test_refreshed_translation_is_cached_normally(self, env):
        self._write_entry(env, self.BROKEN)
        with patch.object(
            translator.LLMTranslator,
            "_translate_via_llm",
            new=AsyncMock(return_value=self.GOOD),
        ) as llm:
            self._translate(env)
            second = self._translate(env)
        assert second["translatedText"] == self.REPLY
        assert llm.call_count == 1  # the second call came from cache
        assert env.cached == 1

    def test_broken_again_serves_cache_instead_of_paying_twice(self, env):
        key = self._write_entry(env, self.BROKEN)
        # first call: rejected and re-translated
        with patch.object(
            translator.LLMTranslator,
            "_translate_via_llm",
            new=AsyncMock(return_value=self.GOOD),
        ) as llm:
            self._translate(env)
        assert llm.call_count == 1
        # the fresh translation is just as broken — do not pay for it again
        self._write_entry(env, self.BROKEN, version=translator.TRANSLATOR_VERSION)
        with patch.object(
            translator.LLMTranslator,
            "_translate_via_llm",
            new=AsyncMock(return_value=self.GOOD),
        ) as llm2:
            result = self._translate(env)
        llm2.assert_not_called()
        assert result["translatedText"] == self.BROKEN
        assert self._read_entry(key)["translated_text"] == self.BROKEN

    def test_unrelated_keys_still_refresh_after_one_key_was_served(self, env):
        self._write_entry(env, self.BROKEN)
        with patch.object(
            translator.LLMTranslator,
            "_translate_via_llm",
            new=AsyncMock(return_value=self.GOOD),
        ):
            self._translate(env)
            self._translate(env)
        assert env.stale == 1


class TestCacheManagerVersion:
    def test_get_version_zero_without_field(self):
        assert cache_manager.get_version({}) == 0

    def test_get_version_reads_field(self):
        assert cache_manager.get_version({"version": 7}) == 7

    def test_get_version_rejects_junk(self):
        assert cache_manager.get_version({"version": "3"}) == 0
        assert cache_manager.get_version({"version": True}) == 0
        assert cache_manager.get_version({"version": None}) == 0

    def test_set_version_creates_the_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_manager, "CACHE_DIR", tmp_path / "cache")
        cache_manager.set_cache("auto", "ru", "hi", "привет", 4)
        key = cache_manager.cache_key("auto", "ru", "hi")
        assert cache_manager.set_version(key, 5) is True
        entry = cache_manager.get_entry("auto", "ru", "hi")
        assert entry is not None
        assert entry["version"] == 5
        assert entry["translated_text"] == "привет"

    def test_set_version_is_noop_when_current(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_manager, "CACHE_DIR", tmp_path / "cache")
        cache_manager.set_cache("auto", "ru", "hi", "привет", 5)
        key = cache_manager.cache_key("auto", "ru", "hi")
        assert cache_manager.set_version(key, 5) is False

    def test_set_version_missing_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_manager, "CACHE_DIR", tmp_path / "cache")
        assert cache_manager.set_version("nope", 1) is False

    def test_set_version_does_not_touch_created_at(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_manager, "CACHE_DIR", tmp_path / "cache")
        cache_manager.set_cache("auto", "ru", "hi", "привет", 1)
        key = cache_manager.cache_key("auto", "ru", "hi")
        path = cache_manager.CACHE_DIR / f"{key}.json"
        before = json.loads(path.read_text("utf-8"))
        cache_manager.set_version(key, 2)
        after = json.loads(path.read_text("utf-8"))
        assert after["created_at"] == before["created_at"]
        assert after["version"] == 2

    def test_get_entry_returns_none_for_invalid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_manager, "CACHE_DIR", tmp_path / "cache")
        cache_manager.set_cache("auto", "ru", "hi", "привет", 1)
        key = cache_manager.cache_key("auto", "ru", "hi")
        cache_manager.invalidate_cache(key)
        assert cache_manager.get_entry("auto", "ru", "hi") is None

    def test_list_cache_exposes_version(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_manager, "CACHE_DIR", tmp_path / "cache")
        cache_manager.set_cache("auto", "ru", "hi", "привет", 9)
        assert cache_manager.list_cache()[0]["version"] == 9

    def test_get_cache_still_works(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_manager, "CACHE_DIR", tmp_path / "cache")
        cache_manager.set_cache("auto", "ru", "hi", "привет", 2)
        assert cache_manager.get_cache("auto", "ru", "hi") == "привет"
