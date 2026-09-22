"""Deterministic Markdown preservation for translation.

LLMs (DeepSeek, Gemma/QwenCoder, ...) inconsistently keep inline Markdown
markers such as ``*action*``, ``**bold**``, backticks, HTML tags/comments and
URLs.  This module replaces every Markdown construct with a numbered, space
padded placeholder (`` {{0}} ``) before the text is sent to a model, and puts
the original markers back afterwards.  Because the markers are never seen by
the model, they cannot be dropped or translated.

For fenced code blocks (```...```) the whole block is masked by default.  With
``translate_fenced=True`` only the fence delimiters are masked, so the text
inside a block remains visible to the translator and is translated; the
delimiters still round-trip verbatim.  Inline code (`` `x` ``) is always
masked whole.

Validated placeholder format: `` {{n}} `` (space padded braces).
"""

import re
from dataclasses import dataclass

# Order matters: block/atomic constructs first, then inline code, then the
# remaining emphasis runs.  A single pass is used so that generated
# placeholders are never re-scanned by later alternatives.

# Constructs that are always preserved verbatim (also inside fenced blocks).
_MASK_INNER_RE = re.compile(
    r"<!--.*?-->"  # HTML comment
    r"|<[a-zA-Z/!][^>]*>"  # HTML tag
    r"|https?://[^\s<>\"'\)\]]+"  # URL
    r"|`[^`\n]+`"  # inline code
    r"|\*+",  # emphasis / action runs ( *, **, ... )
    re.DOTALL,
)

# Full mask: the fenced block is captured as a single token (default).  With
# translate_fenced=True the same alternation tokenises only the fence
# delimiters while the text between them stays visible.
_MASK_RE = re.compile(
    r"```.*?```"  # fenced code block
    r"|" + _MASK_INNER_RE.pattern,
    re.DOTALL,
)

# Matches a whole fenced block — used to strip code from validation text.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

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

    def placeholder(self, index: int) -> str:
        return f"{self.open}{index}{self.close}"


def _pick_format(text: str) -> tuple[str, str]:
    for open_, close in _TOKEN_FORMATS:
        if re.search(re.escape(open_) + r"\d+" + re.escape(close), text):
            continue
        return open_, close
    return _TOKEN_FORMATS[0]


def has_markdown(text: str) -> bool:
    """True if the text contains any construct this module protects."""
    return _MASK_RE.search(text) is not None


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
    """Replace Markdown constructs with numbered, space-separated placeholders.

    A single space is added only where the neighbouring character is not
    already whitespace, so restoring is exact and no spacing is introduced.

    With translate_fenced=True the delimiters of fenced code blocks (```)
    become placeholders while the text between them stays visible, so the
    translator still sees and translates it.  Inline code (`` `x` ``) is always
    masked whole — identifiers are never translated.
    """
    open_, close = _pick_format(text)
    tokens: list[str] = []
    padded: list[str] = []

    def _add(lead: str, token: str, trail: str) -> str:
        index = len(tokens)
        tokens.append(token)
        placeholder = f"{open_}{index}{close}"
        replacement = f"{lead}{placeholder}{trail}"
        padded.append(replacement)
        return replacement

    def _spacing(match: re.Match, s: str) -> tuple[str, str]:
        lead = " " if match.start() > 0 and not s[match.start() - 1].isspace() else ""
        trail = " " if match.end() < len(s) and not s[match.end()].isspace() else ""
        return lead, trail

    def _mask_plain(s: str) -> str:
        def _repl(match: re.Match) -> str:
            lead, trail = _spacing(match, s)
            return _add(lead, match.group(0), trail)

        return _MASK_INNER_RE.sub(_repl, s)

    def _repl(match: re.Match) -> str:
        block = match.group(0)
        lead, trail = _spacing(match, text)
        if translate_fenced and block.startswith("```"):
            parts = _split_fence(block)
            if parts is not None:
                open_part, content_lines, close_line = parts
                open_str = _add(lead, open_part, "")
                if content_lines:
                    inner = _mask_plain("\n".join(content_lines)) + "\n"
                else:
                    inner = ""
                close_str = _add("", close_line, trail)
                return f"{open_str}\n{inner}{close_str}"
        return _add(lead, block, trail)

    masked = _MASK_RE.sub(_repl, text)
    return MaskedText(
        text=masked, tokens=tokens, padded=padded, open=open_, close=close
    )


def restore_markdown(text: str, masked: MaskedText) -> str:
    """Put the original markers back and strip any leftover placeholders."""
    for index, token in enumerate(masked.tokens):
        replacement = masked.padded[index]
        if replacement in text:
            text = text.replace(replacement, token)
        else:
            text = text.replace(masked.placeholder(index), token)
    text = re.sub(re.escape(masked.open) + r"\d*" + re.escape(masked.close), "", text)
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
        f"(звёздочки, код, HTML-теги, ссылки). Сохрани их в переводе ровно как "
        f"есть: не удаляй, не меняй и не переводи их."
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
