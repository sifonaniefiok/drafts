"""The writing session: everything the editor does, minus the terminal.

The full-screen editor (:mod:`drafts.editor`) is a thin layer that forwards
keystrokes here. Keeping this logic free of prompt_toolkit means it can be unit
tested with plain function calls and a fake clock: no terminal required.

When do commits happen? (the *commit policy*)
---------------------------------------------
Saving to disk and committing to git are separate on purpose:

* **Autosave** (every ``autosave_interval`` seconds while there are unsaved
  changes) only writes the file. Your words are safe on disk, but history is
  not cluttered with a commit every few seconds.
* **Ctrl-S** writes the file and commits it, unless the previous commit of
  this session was less than ``commit_interval`` seconds ago. In that case the
  commit is *deferred*: the text is on disk, and it is included in the next
  commit. This debounce stops a habitual Ctrl-S after every sentence from
  producing dozens of near-identical commits.
* **Quitting** always commits whatever is on disk and differs from the last
  commit, so a session ends with everything in history.
* A commit is only created if the file actually differs from the last commit;
  Drafts never makes empty commits.

If the editor is killed, autosaved text is on disk but not committed. The next
``drafts write`` of that draft commits it first as a "Snapshot" commit, so the
new session's commit contains only the new session's work.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from drafts.names import display_name
from drafts.text import count_words
from drafts.workspace import Workspace

DEFAULT_AUTOSAVE_INTERVAL = 30.0
DEFAULT_COMMIT_INTERVAL = 60.0
MESSAGE_SECONDS = 5.0


@dataclass(frozen=True)
class GoalProgress:
    """Progress towards a word goal for this session."""

    target: int
    written: int

    @property
    def fraction(self) -> float:
        return min(1.0, self.written / self.target) if self.target > 0 else 1.0

    @property
    def done(self) -> bool:
        return self.written >= self.target


@dataclass(frozen=True)
class SaveResult:
    """What a save did: whether it wrote the file and which commit it made."""

    written: bool
    commit: str | None = None
    deferred: bool = False  # True if the commit was postponed by the debounce


class WritingSession:
    """State and rules of one editing session on one draft.

    ``clock`` (monotonic seconds) drives autosave and commit debouncing and
    ``wallclock`` provides the time shown in the status line; both can be
    replaced in tests.
    """

    def __init__(
        self,
        workspace: Workspace,
        name: str,
        *,
        goal: int | None = None,
        autosave_interval: float = DEFAULT_AUTOSAVE_INTERVAL,
        commit_interval: float = DEFAULT_COMMIT_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        wallclock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.workspace = workspace
        self.path = workspace.path_for(name)
        self.file_name = self.path.name
        self.goal = goal if goal and goal > 0 else None
        self.autosave_interval = autosave_interval
        self.commit_interval = commit_interval
        self.clock = clock
        self.wallclock = wallclock

        # Commit edits made outside Drafts (or left by a crash) before we start,
        # so that this session's commits contain only this session's work.
        workspace.snapshot(self.file_name)

        self.saved_text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        self.text = self.saved_text
        self.start_words = count_words(self.text)
        self._words = self.start_words
        self._last_commit_at: float | None = None
        self._last_write_at = clock()
        self.commits: list[str] = []
        self.message = ""  # transient feedback shown in the status line
        self._message_at = clock()

    # ------------------------------------------------------------------ state

    def update(self, text: str) -> None:
        """Called by the editor whenever the buffer changes."""
        if text != self.text:
            self.text = text
            self._words = count_words(text)

    @property
    def dirty(self) -> bool:
        """True if the buffer has changes that are not written to disk."""
        return self.text != self.saved_text

    @property
    def word_count(self) -> int:
        return self._words

    @property
    def session_words(self) -> int:
        """Net words added this session (negative if you cut more than you wrote)."""
        return self._words - self.start_words

    @property
    def goal_progress(self) -> GoalProgress | None:
        if self.goal is None:
            return None
        return GoalProgress(self.goal, max(0, self.session_words))

    # ----------------------------------------------------------------- saving

    def write(self) -> bool:
        """Write the buffer to disk if it changed. Returns True if it wrote."""
        if not self.dirty:
            return False
        self.workspace.write(self.file_name, self.text)
        self.saved_text = self.text
        self._last_write_at = self.clock()
        return True

    def autosave_due(self) -> bool:
        return self.dirty and self.clock() - self._last_write_at >= self.autosave_interval

    def autosave(self) -> bool:
        """Write to disk (never commit) if there are changes and the interval passed."""
        if not self.autosave_due():
            return False
        written = self.write()
        if written:
            self.notify("autosaved")
        return written

    def save(self) -> SaveResult:
        """Explicit save (Ctrl-S): write, then commit unless debounced."""
        written = self.write()
        now = self.clock()
        if self._last_commit_at is not None and now - self._last_commit_at < self.commit_interval:
            deferred = self.workspace.is_dirty(self.file_name)
            self.notify("saved · commit pending" if deferred else "saved")
            return SaveResult(written, None, deferred)
        sha = self.commit()
        self.notify(f"saved · committed {sha[:7]}" if sha else "saved")
        return SaveResult(written, sha)

    def commit(self) -> str | None:
        """Commit what is on disk if it differs from the last commit."""
        if not self.path.exists():
            return None
        message = self.workspace.commit_message(self.file_name)
        sha = self.workspace.commit(self.file_name, message)
        if sha:
            self._last_commit_at = self.clock()
            self.commits.append(sha)
        return sha

    def finish(self, save: bool = True) -> str | None:
        """End the session: optionally write the buffer, then commit what's on disk.

        ``save=False`` (quit without saving) discards only the changes made
        since the last save or autosave; anything already on disk is committed.
        """
        if save:
            self.write()
        return self.commit()

    # ------------------------------------------------------------ status line

    def notify(self, message: str) -> None:
        """Show ``message`` in the status line for a few seconds."""
        self.message = message
        self._message_at = self.clock()

    def current_message(self, ttl: float = MESSAGE_SECONDS) -> str:
        """The latest message, or "" once it is older than ``ttl`` seconds."""
        return self.message if self.clock() - self._message_at < ttl else ""

    def status_fields(self) -> list[str]:
        """Pieces of the status line, left to right.

        Kept here rather than in the UI so the exact text is unit-testable.
        """
        fields = [display_name(self.file_name), f"{self.word_count:,} words"]
        fields.append(f"{self.session_words:+,} this session")
        progress = self.goal_progress
        if progress is not None:
            mark = " ✓" if progress.done else ""
            fields.append(
                f"goal {progress.written:,}/{progress.target:,} ({progress.fraction:.0%}){mark}"
            )
        fields.append(self.wallclock().strftime("%H:%M"))
        fields.append("● unsaved" if self.dirty else "saved")
        return fields

    def status_line(self) -> str:
        return "  ·  ".join(self.status_fields())
