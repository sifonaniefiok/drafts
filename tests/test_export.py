from drafts.export import is_safe_url, markdown_to_html, plain_to_html, to_html, to_text

SAMPLE = """# On Attention

Attention is *rare* and **valuable**, like `time`.

- first point
- second point
  continues here

1. one
2. two

> A quote
> over two lines.

```
code <stays> *literal*
```

---

See [the essay](https://example.com/essay?a=1&b=2).
"""


def test_markdown_blocks_and_inline() -> None:
    html = markdown_to_html(SAMPLE)
    assert "<h1>On Attention</h1>" in html
    assert "<em>rare</em>" in html and "<strong>valuable</strong>" in html
    assert "<code>time</code>" in html
    assert "<ul>\n<li>first point</li>\n<li>second point continues here</li>\n</ul>" in html
    assert "<ol>\n<li>one</li>\n<li>two</li>\n</ol>" in html
    assert "<blockquote>\n<p>A quote\nover two lines.</p>\n</blockquote>" in html
    assert "<pre><code>code &lt;stays&gt; *literal*</code></pre>" in html
    assert "<hr>" in html
    assert '<a href="https://example.com/essay?a=1&amp;b=2">the essay</a>' in html


def test_html_export_is_safe() -> None:
    html = markdown_to_html(
        "<script>alert(1)</script>\n\n[click](javascript:alert(1)) "
        "[sneaky](java\tscript:alert(1)) ![x](data:text/html,boom) `<b>*no*</b>`"
    )
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "javascript" not in html.replace("&lt;", "")  # the link target was dropped
    assert 'href="' not in html and "<img" not in html
    assert "<code>&lt;b&gt;*no*&lt;/b&gt;</code>" in html
    assert is_safe_url("https://example.com") and is_safe_url("#notes") and is_safe_url("a.html")
    assert not is_safe_url("JavaScript:alert(1)")


def test_full_page_and_plain_text_drafts() -> None:
    page = to_html("Hello *world*", title="My <Essay>")
    assert page.startswith("<!doctype html>")
    assert "<title>My &lt;Essay&gt;</title>" in page
    assert plain_to_html("Line *one*\nline two\n\nNew <para>") == (
        "<p>Line *one*<br>\nline two</p>\n<p>New &lt;para&gt;</p>"
    )


def test_text_export_has_no_escape_codes_and_wraps() -> None:
    out = to_text(SAMPLE, width=40)
    assert "\x1b[" not in out
    assert "On Attention" in out and "first point" in out
    assert all(len(line) <= 40 for line in out.splitlines())
