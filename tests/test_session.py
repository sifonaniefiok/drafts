"""The editor's logic, tested without a terminal by calling the session directly."""

from datetime import datetime

from drafts.session import WritingSession
from drafts.workspace import Workspace


def make_session(ws: Workspace, clock, name: str = "essay", **kwargs) -> WritingSession:
    kwargs.setdefault("autosave_interval", 30)
    kwargs.setdefault("commit_interval", 60)
    return WritingSession(
        ws, name, clock=clock, wallclock=lambda: datetime(2026, 3, 1, 9, 5), **kwargs
    )


def test_autosave_writes_to_disk_but_never_commits(ws: Workspace, clock) -> None:
    session = make_session(ws, clock)
    session.update("Some words")
    assert session.autosave() is False  # interval not reached yet
    clock.advance(31)
    assert session.autosave() is True
    assert ws.read("essay") == "Some words"
    assert not session.dirty
    session.update("Some more words")
    clock.advance(31)
    assert session.autosave() is True
    assert ws.git.log() == []  # autosaves never create commits


def test_explicit_save_commits_and_is_debounced(ws: Workspace, clock) -> None:
    session = make_session(ws, clock)
    session.update("First sentence.")
    first = session.save()
    assert first.written and first.commit is not None

    clock.advance(10)  # well inside the 60 s commit interval
    session.update("First sentence. Second sentence.")
    second = session.save()
    assert second.written and second.commit is None and second.deferred
    assert ws.read("essay") == "First sentence. Second sentence."  # still safe on disk
    assert len(ws.git.log()) == 1

    clock.advance(60)
    session.update("First sentence. Second sentence. Third.")
    third = session.save()
    assert third.commit is not None
    assert len(ws.git.log()) == 2


def test_finish_commits_pending_work_from_autosave_and_debounce(ws: Workspace, clock) -> None:
    session = make_session(ws, clock)
    session.update("one")
    session.save()  # commit 1
    session.update("one two")
    session.save()  # debounced
    session.update("one two three")
    clock.advance(31)
    session.autosave()  # disk only
    session.update("one two three four")
    sha = session.finish()  # quitting commits everything since commit 1
    assert sha is not None
    log = ws.git.log()
    assert len(log) == 2
    assert log[0].subject == "Edit essay.md (+3 words)"
    assert ws.text_at("essay", "HEAD") == "one two three four"


def test_no_empty_commits_from_repeated_saves(ws: Workspace, clock) -> None:
    session = make_session(ws, clock)
    session.update("text")
    session.save()
    clock.advance(120)
    result = session.save()  # nothing changed since the last commit
    assert result.written is False and result.commit is None and not result.deferred
    assert session.finish() is None
    assert len(ws.git.log()) == 1


def test_quitting_an_untouched_new_draft_creates_nothing(ws: Workspace, clock) -> None:
    session = make_session(ws, clock, name="empty")
    assert not session.dirty
    assert session.finish() is None
    assert not ws.exists("empty")


def test_quit_without_saving_discards_only_unsaved_keystrokes(ws: Workspace, clock) -> None:
    session = make_session(ws, clock)
    session.update("kept by autosave")
    clock.advance(31)
    session.autosave()
    session.update("kept by autosave plus a typo spree")
    sha = session.finish(save=False)
    assert sha is not None
    assert ws.text_at("essay", sha) == "kept by autosave"


def test_session_start_snapshots_outside_edits(ws: Workspace, clock) -> None:
    ws.write("essay", "v1")
    ws.commit("essay", "v1")
    ws.write("essay", "v1 edited in vim")  # e.g. edited elsewhere or a crash
    session = make_session(ws, clock)
    assert ws.git.log()[0].subject.startswith("Snapshot essay.md")
    assert session.text == "v1 edited in vim"
    assert session.session_words == 0


def test_word_counts_goal_and_status_line(ws: Workspace, clock) -> None:
    ws.write("essay", "one two three")
    ws.commit("essay", "start")
    session = make_session(ws, clock, goal=4)
    assert session.word_count == 3
    session.update("one two three four five")
    assert session.session_words == 2
    progress = session.goal_progress
    assert progress is not None and progress.written == 2 and progress.fraction == 0.5
    assert session.status_fields() == [
        "essay",
        "5 words",
        "+2 this session",
        "goal 2/4 (50%)",
        "09:05",
        "● unsaved",
    ]
    session.update("one two three four five six seven")
    session.save()
    assert session.goal_progress.done
    assert session.status_line().endswith("goal 4/4 (100%) ✓  ·  09:05  ·  saved")


def test_cutting_text_gives_negative_session_words(ws: Workspace, clock) -> None:
    ws.write("essay", "a b c d e")
    ws.commit("essay", "start")
    session = make_session(ws, clock, goal=10)
    session.update("a b")
    assert session.session_words == -3
    assert session.goal_progress.written == 0
    assert "-3 this session" in session.status_fields()


def test_status_messages_fade(ws: Workspace, clock) -> None:
    session = make_session(ws, clock)
    session.notify("saved")
    assert session.current_message() == "saved"
    clock.advance(10)
    assert session.current_message() == ""
