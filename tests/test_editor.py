"""Smoke tests for the full-screen editor, driven by fake keystrokes.

prompt_toolkit can read keys from a pipe and render to a dummy output, so the
real Application runs here without a terminal.
"""

from datetime import datetime

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from drafts.editor import Editor, EditorOptions
from drafts.session import WritingSession

CTRL_S = "\x13"
CTRL_Q = "\x11"
CTRL_X = "\x18"
CTRL_T = "\x14"


def run_editor(ws, keys: str, name: str = "essay", **options) -> tuple[Editor, object]:
    session = WritingSession(
        ws, name, autosave_interval=3600, commit_interval=0, wallclock=lambda: datetime(2026, 1, 1)
    )
    editor = Editor(session, EditorOptions(**options))
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        result = editor.run(input=pipe, output=DummyOutput())
    return editor, result


def test_type_save_and_quit(ws) -> None:
    editor, result = run_editor(ws, "Hello world\rSecond line" + CTRL_S + CTRL_Q)
    assert ws.read("essay") == "Hello world\nSecond line"
    assert result.saved
    log = ws.git.log()
    assert len(log) == 1 and log[0].subject == "Create essay.md (4 words)"
    assert editor.session.word_count == 4


def test_quit_with_unsaved_changes_asks_and_saves_on_yes(ws) -> None:
    editor, result = run_editor(ws, "Draft text" + CTRL_Q + "y")
    assert result.saved and result.commit is not None
    assert ws.read("essay") == "Draft text"


def test_quit_with_unsaved_changes_and_answer_no_discards(ws) -> None:
    ws.write("essay", "Kept")
    ws.commit("essay", "start")
    editor, result = run_editor(ws, " and lost" + CTRL_X + "n")
    assert not result.saved and result.commit is None
    assert ws.read("essay") == "Kept"


def test_cancel_quit_keeps_editing_and_prompt_keys_do_not_type(ws) -> None:
    editor, result = run_editor(ws, "abc" + CTRL_Q + "zc" + "def" + CTRL_S + CTRL_Q)
    # "z" was swallowed by the prompt, "c" cancelled it, then typing resumed.
    assert ws.read("essay") == "abcdef"
    assert result.saved


def test_status_toggle_tab_and_typewriter_layout(ws) -> None:
    editor, _ = run_editor(ws, CTRL_T + "\tindented" + CTRL_S + CTRL_Q, typewriter=True, width=40)
    assert editor.show_status is False
    assert ws.read("essay") == "    indented"
