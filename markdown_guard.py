"""Deterministic Markdown preservation for translation.

LLMs (DeepSeek, Gemma/QwenCoder, ...) inconsistently keep inline Markdown
markers such as ``*action*``, ``**bold**``, backticks, HTML tags/comments and
URLs.  This module replaces every Markdown construct with a numbered, space
padded placeholder (`` {{0}} ``) before the text is sent to a model, and puts
the original markers back afterwards.  Because the markers are never seen by
the model, they cannot be dropped or translated.

Validated placeholder format: `` {{n}} `` (space padded braces).
"""

import re
from dataclasses import dataclass

# Order matters: block/atomic constructs first, then inline code, then the
# remaining emphasis runs.  A single pass is used so that generated
# placeholders are never re-scanned by later alternatives.
_MASK_RE = re.compile(
    r"```.*?```"  # fenced code block
    r"|<!--.*?-->"  # HTML comment
    r"|<[a-zA-Z/!][^>]*>"  # HTML tag
    r"|https?://[^\s<>\"'\)\]]+"  # URL
    r"|`[^`\n]+`"  # inline code
    r"|\*+",  # emphasis / action runs ( *, **, ... )
    re.DOTALL,
)

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


def mask_markdown(text: str) -> MaskedText:
    """Replace Markdown constructs with numbered, space-separated placeholders.

    A single space is added only where the neighbouring character is not
    already whitespace, so restoring is exact and no spacing is introduced.
    """
    open_, close = _pick_format(text)
    tokens: list[str] = []
    padded: list[str] = []

    def _repl(match: re.Match) -> str:
        index = len(tokens)
        tokens.append(match.group(0))
        placeholder = f"{open_}{index}{close}"
        lead = (
            " " if match.start() > 0 and not text[match.start() - 1].isspace() else ""
        )
        trail = (
            " " if match.end() < len(text) and not text[match.end()].isspace() else ""
        )
        replacement = f"{lead}{placeholder}{trail}"
        padded.append(replacement)
        return replacement

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


def markdown_instruction(masked: MaskedText) -> str:
    """Prompt suffix that tells the model to keep the placeholders intact."""
    sample = masked.placeholder(0)
    return (
        f"\n\nСлужебные маркеры вида {sample} — это элементы форматирования "
        f"(звёздочки, код, HTML-теги, ссылки). Сохрани их в переводе ровно как "
        f"есть: не удаляй, не меняй и не переводи их."
    )
