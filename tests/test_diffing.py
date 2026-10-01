from drafts.diffing import (
    line_diff,
    render_line_diff,
    render_word_diff,
    summarize,
    word_diff,
    words_added,
)


def test_word_diff_marks_exact_words_and_reconstructs_both_sides() -> None:
    old = "The quick brown fox jumps over the lazy dog."
    new = "The quick red fox leaps over the lazy dog!"
    chunks = word_diff(old, new)
    assert "".join(c.text for c in chunks if c.op != "insert") == old
    assert "".join(c.text for c in chunks if c.op != "delete") == new
    inserted = [c.text for c in chunks if c.op == "insert"]
    assert inserted == ["red", "leaps", "dog!"]
    assert summarize(chunks) == (3, 3)


def test_words_added_counts_rewrites_not_net_change() -> None:
    assert words_added("", "brand new words") == 3
    assert words_added("one two three", "one two") == 0
    # Same length, but two words were rewritten: that is writing.
    assert words_added("I like tea a lot", "I love coffee a lot") == 2


def test_render_word_diff_plain_markers() -> None:
    chunks = word_diff("Attention is rare.", "Attention is rare and generous.")
    text = render_word_diff(chunks, markers=True).plain
    assert text == "Attention is [-rare.-]{+rare and generous.+}"


def test_render_word_diff_collapses_long_unchanged_text() -> None:
    old = " ".join(f"w{i}" for i in range(200))
    new = old.replace("w100", "CHANGED")
    plain = render_word_diff(word_diff(old, new), context=5, markers=True).plain
    assert "{+CHANGED+}" in plain and "[-w100-]" in plain
    assert "[…]" in plain
    assert "w95" in plain and "w105" in plain  # context around the change is kept
    assert "w50" not in plain and "w150" not in plain


def test_line_diff_is_unified_and_coloured() -> None:
    lines = line_diff("a\nb\nc\n", "a\nB\nc\n", "abc1234", "working copy")
    assert lines[:2] == ["--- abc1234", "+++ working copy"]
    assert "-b" in lines and "+B" in lines
    rendered = render_line_diff(lines)
    styles = {str(span.style) for span in rendered.spans}
    assert {"red", "green", "cyan"} <= styles
