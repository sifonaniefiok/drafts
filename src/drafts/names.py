"""Turning what the user types into a safe file name.

A draft name comes straight from the command line (``drafts write "My Essay"``)
and is joined onto the workspace path. Without checks, a name such as
``../../.bashrc`` would let Drafts write outside the workspace, and a name like
``.git`` would clobber the repository itself. This module is the single place
where that is prevented, so every other module can trust the names it gets.
"""

from __future__ import annotations

import re
import unicodedata

#: File extensions Drafts treats as drafts. Anything else gets ``.md`` appended.
EXTENSIONS: tuple[str, ...] = (".md", ".txt")
DEFAULT_EXTENSION = ".md"
MAX_NAME_LENGTH = 120

# Characters we keep: unicode letters/digits/underscore (\w), dash and dot.
# Everything else (quotes, colons, emoji, ...) is dropped so names stay portable
# across filesystems and need no quoting in a shell.
_UNSAFE = re.compile(r"[^\w.\-]+", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_DASHES = re.compile(r"-{2,}")


class InvalidNameError(ValueError):
    """Raised when a draft name cannot be turned into a safe file name."""


def sanitize_name(raw: str) -> str:
    """Return a safe file name (with extension) for the draft name ``raw``.

    Rules, in order:

    * path separators, ``..`` and NUL bytes are rejected outright rather than
      silently rewritten, because they almost always signal a mistake or an
      attack and the user should know;
    * a leading dot is rejected, so drafts are never hidden files and can never
      be ``.git``;
    * whitespace becomes ``-`` and any other unsafe character is dropped;
    * ``.md`` is appended unless the name already ends in ``.md`` or ``.txt``.

    >>> sanitize_name("My Essay")
    'My-Essay.md'
    >>> sanitize_name("notes.txt")
    'notes.txt'
    """
    name = unicodedata.normalize("NFC", raw).strip()
    if not name:
        raise InvalidNameError("a draft name cannot be empty")
    if "/" in name or "\\" in name or "\x00" in name:
        raise InvalidNameError(f"{raw!r}: names cannot contain path separators")
    if ".." in name:
        raise InvalidNameError(f"{raw!r}: names cannot contain '..'")
    if name.startswith("."):
        raise InvalidNameError(f"{raw!r}: names cannot start with '.' (no hidden files)")

    name = _WHITESPACE.sub("-", name)
    name = _UNSAFE.sub("", name)
    name = _DASHES.sub("-", name).strip("-")

    stem, ext = _split_extension(name)
    stem = stem.strip("-.")
    if not stem:
        raise InvalidNameError(f"{raw!r}: no usable characters left after sanitizing")
    stem = stem[:MAX_NAME_LENGTH]
    return stem + ext


def display_name(file_name: str) -> str:
    """Name shown to the user: the file name without a ``.md`` extension.

    ``.txt`` is kept visible so the two kinds of draft can be told apart.
    """
    if file_name.lower().endswith(DEFAULT_EXTENSION):
        return file_name[: -len(DEFAULT_EXTENSION)]
    return file_name


def is_draft_file(file_name: str) -> bool:
    """True for visible files with a draft extension (used when listing)."""
    return not file_name.startswith(".") and file_name.lower().endswith(EXTENSIONS)


def _split_extension(name: str) -> tuple[str, str]:
    lowered = name.lower()
    for ext in EXTENSIONS:
        if lowered.endswith(ext):
            return name[: -len(ext)], ext
    return name, DEFAULT_EXTENSION
