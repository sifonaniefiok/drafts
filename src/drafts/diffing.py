"""Comparing two versions of a draft.

Code is compared line by line, but prose is not: a paragraph is often a single
long line, so changing one word would mark the whole paragraph as changed. The
default here is a *word-level* diff, which highlights exactly the words that
were added or removed. A classic unified line diff is available too.

Both are built on :class:`difflib.SequenceMatcher` from the standard library.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Literal

from rich.text import Text

from drafts.text import count_words

Op = Literal["equal", "insert", "delete"]

# Words (any run of non-space characters) and the whitespace between them are
# separate tokens, so joining the tokens reproduces the text exactly.
_TOKEN = re.compile(r"\s+|\S+")

#: Unchanged words kept around each change when collapsing long equal spans.
CONTEXT_WORDS = 12


@dataclass(frozen=True)
class Chunk:
    """A run of text that is unchanged, inserted or deleted."""

    op: Op
    text: str


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text)


def word_diff(old: str, new: str) -> list[Chunk]:
    """Diff ``old`` and ``new`` word by word.

    ``autojunk`` is disabled: by default difflib ignores tokens that appear
    very often (like "the" or a single space) in long inputs, which makes the
    diff of a long essay much worse.
    """
    a, b = tokenize(old), tokenize(new)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    chunks: list[Chunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            chunks.append(Chunk("equal", "".join(a[i1:i2])))
            continue
        if i2 > i1:  # "delete" or the old side of "replace"
            chunks.append(Chunk("delete", "".join(a[i1:i2])))
        if j2 > j1:  # "insert" or the new side of "replace"
            chunks.append(Chunk("insert", "".join(b[j1:j2])))
    return chunks


def summarize(chunks: list[Chunk]) -> tuple[int, int]:
    """(words added, words removed) according to a word diff."""
    added = sum(count_words(c.text) for c in chunks if c.op == "insert")
    removed = sum(count_words(c.text) for c in chunks if c.op == "delete")
    return added, removed


def words_added(old: str, new: str) -> int:
    """Words written between two versions: inserted words, not the net change.

    Rewriting a sentence of ten words with ten new words counts as ten words
    written, even though the length of the draft did not change.
    """
    return summarize(word_diff(old, new))[0]


def render_word_diff(
    chunks: list[Chunk], context: int = CONTEXT_WORDS, markers: bool = False
) -> Text:
    """Render a word diff as Rich text: deletions red and struck through,
    insertions green and underlined, long unchanged stretches collapsed.

    With ``markers=True`` changes are also wrapped in ``[-deleted-]`` and
    ``{+inserted+}`` (the same notation as ``git diff --word-diff=plain``), so
    the diff still makes sense when colours are unavailable, e.g. in a pipe.
    """
    out = Text()
    last = len(chunks) - 1
    for index, chunk in enumerate(chunks):
        if chunk.op in ("insert", "delete"):
            # Keep surrounding whitespace outside the highlight: "{+ word+}"
            # and underlined spaces are harder to read than " {+word+}".
            core = chunk.text.strip()
            lead = chunk.text[: len(chunk.text) - len(chunk.text.lstrip())]
            trail = chunk.text[len(chunk.text.rstrip()) :] if core else ""
            if chunk.op == "insert":
                styled, style = (f"{{+{core}+}}" if markers else core), "bold green underline"
            else:
                styled, style = (f"[-{core}-]" if markers else core), "red strike"
            out.append(lead)
            if core:
                out.append(styled, style=style)
            out.append(trail)
        else:
            out.append(_collapse(chunk.text, context, index == 0, index == last), style="dim")
    return out


def _collapse(text: str, context: int, is_first: bool, is_last: bool) -> str:
    """Shorten unchanged text, keeping ``context`` words next to each change."""
    tokens = tokenize(text)
    word_positions = [i for i, tok in enumerate(tokens) if not tok.isspace()]
    keep_head = 0 if is_first else context
    keep_tail = 0 if is_last else context
    if len(word_positions) <= keep_head + keep_tail + 2:
        return text
    head = "".join(tokens[: word_positions[keep_head]]) if keep_head else ""
    tail = "".join(tokens[word_positions[-keep_tail] :]) if keep_tail else ""
    if head and not head[-1].isspace():
        head += " "
    if tail and not tail[0].isspace():
        tail = " " + tail
    return f"{head}[…]{tail}"


def line_diff(old: str, new: str, old_label: str, new_label: str) -> list[str]:
    """Unified line diff (like ``git diff``) as a list of lines."""
    return list(
        difflib.unified_diff(old.splitlines(), new.splitlines(), old_label, new_label, lineterm="")
    )


def render_line_diff(lines: list[str]) -> Text:
    """Colour a unified diff the way ``git diff`` does."""
    out = Text()
    for line in lines:
        if line.startswith(("+++", "---")):
            style = "bold"
        elif line.startswith("@@"):
            style = "cyan"
        elif line.startswith("+"):
            style = "green"
        elif line.startswith("-"):
            style = "red"
        else:
            style = "dim"
        out.append(line + "\n", style=style)
    return out
