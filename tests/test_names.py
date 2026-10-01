import pytest

from drafts.names import InvalidNameError, display_name, is_draft_file, sanitize_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("essay", "essay.md"),
        ("My Essay", "My-Essay.md"),
        ("  spaced   out  ", "spaced-out.md"),
        ("notes.txt", "notes.txt"),
        ("Notes.MD", "Notes.md"),
        ("chapter.v2", "chapter.v2.md"),
        ("what? why!", "what-why.md"),
        ("café notes", "café-notes.md"),
        ("日記", "日記.md"),
    ],
)
def test_sanitize_produces_safe_names(raw: str, expected: str) -> None:
    assert sanitize_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "../escape", "a/b", "a\\b", "..", "x..y", ".hidden", ".git", "nul\x00byte", "???"],
)
def test_sanitize_rejects_unsafe_names(raw: str) -> None:
    with pytest.raises(InvalidNameError):
        sanitize_name(raw)


def test_path_for_always_stays_inside_workspace(ws) -> None:
    for raw in ["essay", "My Essay", "notes.txt", "a:b*c"]:
        path = ws.path_for(raw)
        assert path.parent == ws.root
        assert not path.name.startswith(".")


def test_display_name_and_draft_detection() -> None:
    assert display_name("essay.md") == "essay"
    assert display_name("notes.txt") == "notes.txt"
    assert is_draft_file("essay.md") and is_draft_file("notes.txt")
    assert not is_draft_file(".essay.md.tmp")
    assert not is_draft_file("picture.png")
