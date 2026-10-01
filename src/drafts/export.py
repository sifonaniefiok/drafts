"""Exporting drafts to HTML or formatted plain text.

HTML export uses a small built-in Markdown converter instead of a third-party
library, to keep dependencies to Rich and prompt_toolkit. It supports the
subset of Markdown people use for prose:

* headings (``#`` to ``######``), paragraphs, horizontal rules (``---``);
* ``*emphasis*``, ``**strong**``, ``~~strike~~``, ```inline code```;
* links ``[text](url)`` and images ``![alt](url)``;
* unordered (``-``, ``*``, ``+``) and ordered (``1.``) lists, one level deep;
* blockquotes (``>``) and fenced code blocks (````` ``` `````).

It is *safe by construction*: all text is HTML-escaped before any Markdown is
interpreted, so raw HTML in a draft is shown as text rather than executed, and
link/image URLs are only kept for ``http``, ``https``, ``mailto`` or relative
targets, so ``javascript:`` links cannot sneak through.

Plain-text export renders the Markdown with Rich (headings, lists, rules and
wrapping at a chosen width) without any colour codes.
"""

from __future__ import annotations

import html
import io
import re
from urllib.parse import urlparse

from rich.console import Console
from rich.markdown import Markdown

SAFE_SCHEMES = {"", "http", "https", "mailto"}

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_UL_ITEM = re.compile(r"^\s{0,3}[-*+]\s+(.*)$")
_OL_ITEM = re.compile(r"^\s{0,3}\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")

_CODE_SPAN = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_EM_STAR = re.compile(r"\*(?=\S)(.+?)(?<=\S)\*")
_EM_UNDERSCORE = re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")


def is_safe_url(url: str) -> bool:
    """True for URLs that cannot run script when clicked."""
    cleaned = html.unescape(url).strip()
    # Browsers ignore control characters and whitespace inside a scheme
    # ("java\tscript:"), so remove them before looking at it.
    cleaned = re.sub(r"[\x00-\x20]", "", cleaned)
    return urlparse(cleaned).scheme.lower() in SAFE_SCHEMES


def render_inline(text: str) -> str:
    """Convert inline Markdown in one block of text to HTML (input is raw text)."""
    escaped = html.escape(text, quote=True)

    # Code spans are cut out first and swapped for placeholders, so that the
    # emphasis rules below cannot change what is inside them.
    codes: list[str] = []

    def stash(match: re.Match[str]) -> str:
        codes.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = _CODE_SPAN.sub(stash, escaped)

    def image(match: re.Match[str]) -> str:
        alt, url = match.group(1), match.group(2)
        return f'<img src="{url}" alt="{alt}">' if is_safe_url(url) else alt

    def link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        return f'<a href="{url}">{label}</a>' if is_safe_url(url) else label

    out = _IMAGE.sub(image, out)
    out = _LINK.sub(link, out)
    out = _STRONG.sub(r"<strong>\2</strong>", out)
    out = _EM_STAR.sub(r"<em>\1</em>", out)
    out = _EM_UNDERSCORE.sub(r"<em>\1</em>", out)
    out = _STRIKE.sub(r"<del>\1</del>", out)
    return re.sub("\x00(\\d+)\x00", lambda m: codes[int(m.group(1))], out)


def markdown_to_html(text: str) -> str:
    """Convert Markdown to an HTML fragment (block structure + inline)."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if fence := _FENCE.match(line):
            marker = fence.group(1)
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                body.append(lines[i])
                i += 1
            i += 1  # skip the closing fence (or run off the end if unclosed)
            out.append(f"<pre><code>{html.escape(chr(10).join(body))}</code></pre>")
            continue

        if heading := _HEADING.match(line):
            level = len(heading.group(1))
            out.append(f"<h{level}>{render_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if _RULE.match(line):
            out.append("<hr>")
            i += 1
            continue

        if _QUOTE.match(line):
            quoted: list[str] = []
            while i < len(lines) and (m := _QUOTE.match(lines[i])):
                quoted.append(m.group(1))
                i += 1
            out.append(f"<blockquote>\n{markdown_to_html(chr(10).join(quoted))}\n</blockquote>")
            continue

        for pattern, tag in ((_UL_ITEM, "ul"), (_OL_ITEM, "ol")):
            if pattern.match(line):
                items: list[str] = []
                while i < len(lines) and lines[i].strip():
                    if m := pattern.match(lines[i]):
                        items.append(m.group(1))
                    elif items:  # indented continuation of the previous item
                        items[-1] += " " + lines[i].strip()
                    i += 1
                rendered = "\n".join(f"<li>{render_inline(item)}</li>" for item in items)
                out.append(f"<{tag}>\n{rendered}\n</{tag}>")
                break
        else:
            paragraph: list[str] = []
            while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]):
                paragraph.append(lines[i].strip())
                i += 1
            if not paragraph:  # a block start we could not consume; avoid looping
                paragraph.append(lines[i].strip())
                i += 1
            out.append(f"<p>{render_inline(chr(10).join(paragraph))}</p>")
    return "\n".join(out)


def _starts_block(line: str) -> bool:
    return any(p.match(line) for p in (_HEADING, _RULE, _FENCE, _UL_ITEM, _OL_ITEM, _QUOTE))


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ max-width: 38rem; margin: 3rem auto; padding: 0 1rem;
         font: 1.1rem/1.6 Georgia, "Times New Roman", serif; color: #222; }}
  pre, code {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9em; }}
  pre {{ background: #f5f5f5; padding: 0.75rem; overflow-x: auto; }}
  blockquote {{ margin-left: 0; padding-left: 1rem; border-left: 3px solid #ccc; color: #555; }}
  img {{ max-width: 100%; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def plain_to_html(text: str) -> str:
    """HTML for a plain-text (.txt) draft: escaped paragraphs, no Markdown."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return "\n".join(
        "<p>" + html.escape(p).replace("\n", "<br>\n") + "</p>" for p in paragraphs if p.strip()
    )


def to_html(text: str, title: str, markdown: bool = True) -> str:
    """A complete, standalone HTML page for the draft."""
    body = markdown_to_html(text) if markdown else plain_to_html(text)
    return _PAGE.format(title=html.escape(title), body=body)


def to_text(text: str, width: int = 72) -> str:
    """Render Markdown as formatted plain text, wrapped at ``width`` columns."""
    buffer = io.StringIO()
    console = Console(
        file=buffer, width=width, color_system=None, force_terminal=False, legacy_windows=False
    )
    console.print(Markdown(text))
    return "\n".join(line.rstrip() for line in buffer.getvalue().splitlines()) + "\n"
