"""Word counting for prose written in Markdown or plain text.

Counting words sounds trivial (``len(text.split())``) but that rule counts
Markdown syntax (``#``, ``-``, ``>``, ``---``) as words, counts a link's URL,
and treats a whole sentence of Chinese as a single word. Writers notice when a
word count is wrong, so the rules here are explicit and covered by tests:

* a *word* is a whitespace-separated token containing at least one letter or
  digit, so bare punctuation and Markdown markers are ignored (numbered-list
  markers such as ``1.`` at the start of a line are ignored too);
* ``**bold**``, ``don't`` and ``well-known`` each count as one word;
* em and en dashes separate words (``this—that`` is two words);
* in a link ``[text](url)`` only the text is counted;
* fenced code blocks (````` ``` `````) are not prose and are skipped, while
  inline code is counted like any other text;
* each CJK ideograph or kana character counts as one word, which is the
  convention used by most word processors for languages written without spaces.
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"^\s*(```|~~~)")
_ORDERED_MARKER = re.compile(r"^[ \t]*\d+[.)](?=\s)", re.MULTILINE)
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_DASH = re.compile(r"[\u2013\u2014]")
# CJK Unified Ideographs (+ Extension A), Hiragana, Katakana, CJK compatibility.
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def strip_code_fences(text: str) -> str:
    """Remove fenced code blocks (fence lines included) from ``text``.

    An unclosed fence runs to the end of the text, which matches how Markdown
    renderers treat it.
    """
    kept: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in text.splitlines():
        match = _FENCE.match(line)
        if match and (not in_fence or match.group(1) == fence_marker):
            in_fence = not in_fence
            fence_marker = match.group(1)
            continue
        if not in_fence:
            kept.append(line)
    return "\n".join(kept)


def words(text: str) -> list[str]:
    """Return the tokens of ``text`` that count as words (see module docstring)."""
    prose = strip_code_fences(text)
    prose = _ORDERED_MARKER.sub("", prose)  # "1." starts a list item; it is not a word
    prose = _LINK.sub(r" \1 ", prose)
    prose = _DASH.sub(" ", prose)
    prose = _CJK.sub(lambda m: f" {m.group(0)} ", prose)
    return [token for token in prose.split() if any(ch.isalnum() for ch in token)]


def count_words(text: str) -> int:
    """Number of words in ``text``."""
    return len(words(text))
