"""Deterministic Markdown preservation for translation.

LLMs (DeepSeek, Gemma/QwenCoder, ...) inconsistently keep Markdown markers, and
they drop block-level ones almost every time: ``## Heading`` loses its ``##``,
``---`` disappears, a two-space hard break is stripped as trailing whitespace.
This module replaces every Markdown construct with a numbered placeholder
(`` {{0}} ``) before the text is sent to a model, and puts the original markers
back afterwards.  Because the markers are never seen by the model, they cannot
be dropped, reordered or translated.

Two passes run over the text:

1. *block pass* — line-leading constructs (ATX headings, thematic breaks,
   setext rules, blockquote markers, two-space hard breaks, box-drawing rules)
   and the brackets of ``[text](url)`` / ``![alt](url)``.  Only the marker is
   masked, so heading text and link text are still translated.
2. *inline pass* — HTML comments/tags, URLs, inline code, emphasis runs, and
   fenced code blocks.

Fenced code blocks are skipped by the block pass and handled by the inline
pass: the whole block is masked by default; with ``translate_fenced=True`` only
the fence delimiters are masked, so the text inside a block stays visible to
the translator and is translated.  Inline code (`` `x` ``) is always masked
whole.

Tokens from the block pass are marked *structural* — losing one of those means
the translation lost document structure, not just formatting.

Validated placeholder format: ``{{n}}`` (braces).  A format absent from the
source text is chosen to avoid colliding with literal ``{{0}}``-style text.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Static form of the inline patterns, used only to probe whether a text has
# anything to protect.  `mask_markdown` compiles its own copy that cannot
# swallow a placeholder (see `_build_inline_regexes`).
_MASK_PROBE_INNER = (
    r"<!--.*?-->"  # HTML comment
    r"|<[a-zA-Z/!][^>]*>"  # HTML tag
    r"|https?://[^\s<>\"'\)\]]+"  # URL
    r"|`[^`\n]+`"  # inline code
    r"|\*+"  # emphasis / action runs ( *, **, ... )
)

# Full mask: the fenced block is captured as a single token (default).  With
# translate_fenced=True the same alternation tokenises only the fence
# delimiters while the text between them stays visible.
_MASK_RE = re.compile(r"```.*?```" + "|" + _MASK_PROBE_INNER, re.DOTALL)


def _build_inline_regexes(open_: str) -> tuple[re.Pattern, re.Pattern]:
    """Compile the inline patterns so they cannot swallow a placeholder.

    The block pass runs first and leaves ``{{0}}``-style markers in the text.
    A placeholder contains no character the URL pattern excludes, so without
    this guard a URL would absorb the marker that follows it and the marker
    would be lost on restore.  Every other inline pattern needs a delimiter the
    placeholders never contain, so only the URL body needs the guard.
    """
    not_placeholder = f"(?!{re.escape(open_)})"
    inner = (
        r"<!--.*?-->"  # HTML comment
        r"|<[a-zA-Z/!][^>]*>"  # HTML tag
        rf"|https?://(?:{not_placeholder}[^\s<>\"'\)\]])+"  # URL
        r"|`[^`\n]+`"  # inline code
        r"|\*+"  # emphasis / action runs ( *, **, ... )
    )
    full = r"```.*?```" + "|" + inner
    return re.compile(inner, re.DOTALL), re.compile(full, re.DOTALL)


# Matches a whole fenced block — used to strip code from validation text.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

# Splits text into alternating [plain, fence, plain, ...] so the block pass can
# leave fenced code alone.  An unterminated fence matches up to the end of the
# text, which is the conservative choice: its content stays unmasked.
_FENCE_SPLIT_RE = re.compile(r"(```.*?(?:```|\Z))", re.DOTALL)

# --- block-level constructs, matched at the start of a line ------------------
# Hard break: two or more spaces at the end of a content line.  The model
# strips these as trailing whitespace, so they are masked as a token.
_HARD_BREAK_RE = re.compile(r"(?<=\S)[ \t]{2,}(?=\r?$)", re.M)

# Box-drawing rules: ───── / ═════ / ━━━━━ (and runs broken by spaces).
# No trailing newline inside the token: the line break has to stay in the
# text, otherwise the placeholder ends up glued to the next line and the
# model cannot tell it is a separator.  It also keeps tokens free of `\r`,
# so a CRLF source and an LF translation produce identical tokens.
_BOX_RULE_RE = re.compile(
    r"^[ \t]*(?:[\u2500-\u257f][ \t]*){3,}", re.M
)
# Thematic break: --- / *** / ___ / - - -   (line text only, no newline).
_RULE_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*", re.M)

# Setext heading rule: === on a line of its own.
_SETEXT_RE = re.compile(r"^ {0,3}=+[ \t]*", re.M)

# ATX heading: the marker runs (and any closing run) are masked, the text
# between them stays visible.  Requires a space after the hashes, so `#NoSpace`
# and `####### seven` stay plain text as in CommonMark.
_ATX_RE = re.compile(
    r"^(?P<pre>[ ]{0,3}#{1,6}[ \t]+)"
    r"(?:(?P<body>[^\r\n]*?)(?P<close>[ \t]+#+[ \t]*$)|(?P<rest>[^\r\n]*))$",
    re.M,
)

# Blockquote marker run: > / >> / > quote.
_QUOTE_RE = re.compile(r"^ {0,3}(?:>[ \t]?)+", re.M)

# Markdown link or image.  Both bracket groups become one token each, the label
# between them stays visible and is translated.
_LINK_RE = re.compile(
    r"(?P<open>!?\[)"
    r"(?P<label>(?:[^\[\]\\\r\n]|\\.)*)"
    r"(?P<close>\]\((?:[^()\r\n]|\([^()\r\n]*\))*\))"
)

# A rule line at the very end of the text, with the whitespace that separated
# it from the paragraph before and the whitespace that closes it.  A placeholder
# alone on the last line is the one position a model reliably drops, so this is
# remembered separately and put back in restore_markdown.
_TRAILING_RULE_RE = re.compile(
    r"((?:[ \t]*\r?\n)+)[ \t]*"
    r"(?P<rule>-{3,}|\*{3,}|_{3,}|={2,}"
    r"|[\u2500-\u257f](?:[ \t]*[\u2500-\u257f]){2,})"
    r"(?P<tail>[ \t]*(?:\r?\n)?)\Z"
)

# Block rules, applied in this order to the parts of the text outside fenced
# code.  Every rule emits structural tokens and leaves the text between markers
# (heading text, link label) visible for the inline pass and for translation.

_Add = Callable[..., str]


def _mask_whole(match: re.Match, add: _Add, pos: int) -> str:
    """Mask the whole match as one structural token."""
    return add("", match.group(0), "", True, pos)


def _mask_atx(match: re.Match, add: _Add, pos: int) -> str:
    """Mask the heading marker, the heading text stays, closing run is masked."""
    out = add("", match.group("pre"), "", True, pos)
    closing = match.group("close")
    if closing is None:
        return out + (match.group("rest") or "")
    return out + (match.group("body") or "") + add("", closing, "", True)


def _mask_link(match: re.Match, add: _Add, pos: int) -> str:
    """Mask the opening bracket and the whole `](destination)` part."""
    return (
        add("", match.group("open"), "", True, pos)
        + match.group("label")
        + add("", match.group("close"), "", True)
    )


_BLOCK_RULES: tuple[tuple[re.Pattern, Callable[[re.Match, _Add, int], str]], ...] = (
    (_LINK_RE, _mask_link),
    (_HARD_BREAK_RE, _mask_whole),
    (_BOX_RULE_RE, _mask_whole),
    (_RULE_RE, _mask_whole),
    (_SETEXT_RE, _mask_whole),
    (_ATX_RE, _mask_atx),
    (_QUOTE_RE, _mask_whole),
)

_BLOCK_PATTERNS: tuple[re.Pattern, ...] = tuple(rx for rx, _ in _BLOCK_RULES)

_TOKEN_FORMATS: tuple[tuple[str, str], ...] = (
    ("{{", "}}"),
    ("[[", "]]"),
    ("<<", ">>"),
    ("((", "))"),
)


@dataclass
class MaskedText:
    text: str
    tokens: list[str]
    padded: list[str]
    open: str
    close: str
    structural: list[bool] = field(default_factory=list)
    # (token index, separator, rule, closing whitespace) for a rule line at the
    # very end of the source; restored in restore_markdown if the model dropped
    # it
    trailing_rule: tuple[int, str, str, str] | None = None

    def placeholder(self, index: int) -> str:
        return f"{self.open}{index}{self.close}"

    def is_structural(self, index: int) -> bool:
        """True if the token carries document structure, not just formatting."""
        if index < len(self.structural):
            return self.structural[index]
        return False


def _pick_format(text: str) -> tuple[str, str]:
    for open_, close in _TOKEN_FORMATS:
        if re.search(re.escape(open_) + r"\d+" + re.escape(close), text):
            continue
        return open_, close
    return _TOKEN_FORMATS[0]


def _plain_segments(text: str) -> list[str]:
    """Text with fenced code blocks removed (the fences are not returned)."""
    return [part for i, part in enumerate(_FENCE_SPLIT_RE.split(text)) if i % 2 == 0]


def has_markdown(text: str) -> bool:
    """True if the text contains any construct this module protects."""
    if _MASK_RE.search(text) is not None:
        return True
    return any(
        rx.search(segment)
        for segment in _plain_segments(text)
        for rx in _BLOCK_PATTERNS
    )


def without_fenced_blocks(text: str) -> str:
    """Strip fenced code blocks (```...```) from a text.

    Used for language validation: code inside fences may legitimately stay in
    its original script (identifiers, strings), so only the surrounding prose
    is checked against the target language.
    """
    return _FENCE_RE.sub("", text)


def _split_fence(block: str):
    """Split a fenced block into (opening tag, content lines, closing tag).

    Returns None when the block cannot be split into an opening line and a
    closing fence line (e.g. a single-line fence), in which case it is masked
    as one token.
    """
    nl = block.find("\n")
    if nl == -1:
        return None
    open_part = block[:nl]
    lines = block[nl + 1 :].split("\n")
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].lstrip().startswith("```"):
            return open_part, lines[:i], lines[i]
    return None


def mask_markdown(text: str, translate_fenced: bool = False) -> MaskedText:
    """Replace Markdown constructs with numbered placeholders.

    Block pass first (headings, rules, quotes, hard breaks, link brackets) over
    the text outside fenced code, then the inline pass (HTML, URLs, inline
    code, emphasis, fences).  Both passes share one token counter, so every
    index is unique and ``restore_markdown`` puts the original text back.

    Inline markers get a single space only where the neighbouring character is
    not already whitespace, so restoring is exact and no spacing is introduced.
    Block tokens already carry their own spacing and are inserted verbatim.

    With translate_fenced=True the delimiters of fenced code blocks (```)
    become placeholders while the text between them stays visible, so the
    translator still sees and translates it.  Inline code (`` `x` ``) is always
    masked whole — identifiers are never translated.
    """
    open_, close_ = _pick_format(text)
    inner_re, full_re = _build_inline_regexes(open_)
    tokens: list[str] = []
    padded: list[str] = []
    structural: list[bool] = []
    # offset of each token in the source, or None when the token came from the
    # inline pass and its position is not needed
    positions: list[int | None] = []

    def _add(
        lead: str,
        token: str,
        trail: str,
        is_struct: bool = False,
        pos: int | None = None,
    ) -> str:
        index = len(tokens)
        tokens.append(token)
        structural.append(is_struct)
        positions.append(pos)
        placeholder = f"{open_}{index}{close_}"
        replacement = f"{lead}{placeholder}{trail}"
        padded.append(replacement)
        return replacement

    def _mask_blocks(segment: str, offset: int) -> str:
        for rx, handler in _BLOCK_RULES:
            segment = rx.sub(
                lambda m, _h=handler: _h(m, _add, offset + m.start()), segment
            )
        return segment

    parts = _FENCE_SPLIT_RE.split(text)
    # offset of each part in the original text, so token positions can be found
    _span: list[int] = []
    _at = 0
    for part in parts:
        _span.append(_at)
        _at += len(part)
    staged = "".join(
        part if i % 2 else _mask_blocks(part, _span[i]) for i, part in enumerate(parts)
    )

    def _spacing(match: re.Match, s: str) -> tuple[str, str]:
        lead = " " if match.start() > 0 and not s[match.start() - 1].isspace() else ""
        trail = " " if match.end() < len(s) and not s[match.end()].isspace() else ""
        return lead, trail

    def _mask_plain(s: str) -> str:
        def _repl(match: re.Match) -> str:
            lead, trail = _spacing(match, s)
            return _add(lead, match.group(0), trail)

        return inner_re.sub(_repl, s)

    def _repl(match: re.Match) -> str:
        block = match.group(0)
        lead, trail = _spacing(match, staged)
        if translate_fenced and block.startswith("```"):
            parts_ = _split_fence(block)
            if parts_ is not None:
                open_part, content_lines, close_line = parts_
                open_str = _add(lead, open_part, "")
                if content_lines:
                    inner = _mask_plain("\n".join(content_lines)) + "\n"
                else:
                    inner = ""
                close_str = _add("", close_line, trail)
                return f"{open_str}\n{inner}{close_str}"
        return _add(lead, block, trail)

    masked = full_re.sub(_repl, staged)
    trailing = _TRAILING_RULE_RE.search(text)
    trailing_index: int | None = None
    if trailing is not None:
        start, end = trailing.start("rule"), trailing.end("rule")
        for i, pos in enumerate(positions):
            if pos is not None and start <= pos <= end:
                trailing_index = i
                break
    return MaskedText(
        text=masked,
        tokens=tokens,
        padded=padded,
        open=open_,
        close=close_,
        structural=structural,
        trailing_rule=(
            (
                trailing_index,
                trailing.group(1),
                trailing.group("rule"),
                trailing.group("tail"),
            )
            if trailing is not None and trailing_index is not None
            else None
        ),
    )


def restore_markdown(text: str, masked: MaskedText) -> str:
    """Put the original markers back and strip any leftover placeholders.

    A rule line that ended the source is re-appended if the model dropped it —
    a placeholder alone on the last line is the one spot it reliably loses, and
    a missing separator at the end of a message is visible to the client.  The
    whitespace around the rule is the source's own, folded to the line ending
    the translation ended up with, so a blank line before the rule stays a
    blank line and a setext underline stays an underline.
    """
    trailing = masked.trailing_rule
    dropped = trailing is not None and masked.placeholder(trailing[0]) not in text
    for index, token in enumerate(masked.tokens):
        replacement = masked.padded[index]
        if replacement in text:
            text = text.replace(replacement, token)
        else:
            text = text.replace(masked.placeholder(index), token)
    text = re.sub(re.escape(masked.open) + r"\d*" + re.escape(masked.close), "", text)
    if dropped and trailing is not None:
        _index, separator, rule, tail = trailing
        eol = "\r\n" if "\r\n" in text else "\n"

        def _fold(ws: str) -> str:
            return ws.replace("\r\n", "\n").replace("\n", eol)

        text = text.rstrip() + _fold(separator) + rule + _fold(tail)
    return text


def missing_placeholders(text: str, masked: MaskedText) -> list[int]:
    """Indices of placeholders the model dropped or altered."""
    return [
        index
        for index in range(len(masked.tokens))
        if masked.placeholder(index) not in text
    ]


def markdown_instruction(masked: MaskedText, translate_fenced: bool = False) -> str:
    """Prompt suffix that tells the model to keep the placeholders intact."""
    sample = masked.placeholder(0)
    base = (
        f"\n\nСлужебные маркеры вида {sample} — это элементы форматирования "
        f"(звёздочки, код, HTML-теги, ссылки, скобки ссылок и картинок, "
        f"заголовки, цитаты, разделители). Сохрани их в переводе ровно как "
        f"есть: не удаляй, не меняй и не переводи их."
    )
    if any(masked.structural):
        base += (
            f"\n\nМаркер в начале строки — это заголовок, цитата или "
            f"разделитель; маркер в одиночку на строке — горизонтальный "
            f"разделитель; маркер в конце строки — невидимые пробелы, которые "
            f"делают перенос строки. Не убирай их и не меняй количество пустых "
            f"строк вокруг."
        )
    if translate_fenced and any(
        t.startswith("```") and "\n" not in t for t in masked.tokens
    ):
        base += (
            f"\n\nМаркеры на отдельных строках ограничивают блоки кода. "
            f"Весь текст между ними — обычный текст: переводи его наравне "
            f"со всем остальным, а сами маркеры сохрани нетронутыми."
        )
    return base
