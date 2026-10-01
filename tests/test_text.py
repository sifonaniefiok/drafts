import pytest

from drafts.text import count_words, strip_code_fences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("   \n\t  \n", 0),
        ("one two  three\nfour", 4),
        # Markdown syntax on its own is not a word, but text inside it is.
        ("# Title\n\n- first item\n- second\n\n> quoted line\n\n---\n", 6),
        ("**bold** and *italic* and `code`", 5),
        ("1. first\n2. second", 2),
        # Contractions and hyphenated words are single words; dashes split.
        ("don't stop — well-known facts", 4),
        ("this—that and here–there", 5),
        # Only the visible text of a link counts, not its URL.
        ("read [the docs](https://example.com/a/very/long/url) now", 4),
        ("![a diagram](img.png)", 2),
        # Bare punctuation and emoji are not words; numbers are.
        ("Wait ... what ?! 🙂", 2),
        ("In 2026 we wrote 3 drafts", 6),
    ],
)
def test_count_words_prose_and_markdown(text: str, expected: int) -> None:
    assert count_words(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("naïve café über", 3),
        ("مرحبا بالعالم", 2),
        ("Привет мир", 2),
        ("我爱你", 3),  # each ideograph counts as a word
        ("私はコーヒーが好き", 9),  # kana + kanji, one word per character
        ("Hello 世界", 3),
    ],
)
def test_count_words_unicode(text: str, expected: int) -> None:
    assert count_words(text) == expected


def test_fenced_code_is_not_prose() -> None:
    text = "Before the code.\n\n```python\ndef f(x):\n    return x * 2\n```\n\nAfter it."
    assert count_words(text) == 5
    assert "return" not in strip_code_fences(text)


def test_unclosed_fence_runs_to_end_and_tilde_fences_work() -> None:
    assert count_words("prose here\n```\ncode never closed") == 2
    assert count_words("~~~\nignored words\n~~~\ncounted") == 1
