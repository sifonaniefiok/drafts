"""The workspace: a folder of plain-text drafts that is also a git repository.

This module owns the rules for *where* drafts live and *how* they become
commits. The CLI and the editor never call git directly; they ask the
workspace to read, write, commit, list or restore a draft by name.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from drafts.gitrepo import Commit, GitError, GitRepo
from drafts.names import display_name, is_draft_file, sanitize_name
from drafts.text import count_words

ENV_VAR = "DRAFTS_DIR"
DEFAULT_DIR = "~/drafts"
RESTORE_PREFIX = "Restore "


class DraftNotFoundError(LookupError):
    """The requested draft (or version of a draft) does not exist."""


@dataclass(frozen=True)
class DraftInfo:
    """Summary of one draft, used by ``drafts list``."""

    file_name: str
    name: str
    words: int
    modified: datetime
    commits: int


@dataclass(frozen=True)
class Version:
    """One committed version of a draft, used by ``drafts history``."""

    commit: Commit
    words: int
    delta: int  # words compared with the previous version of the same file


def default_root(env: Mapping[str, str] | None = None) -> Path:
    """Workspace location: ``$DRAFTS_DIR`` if set, otherwise ``~/drafts``."""
    env = os.environ if env is None else env
    return Path(env.get(ENV_VAR) or DEFAULT_DIR).expanduser()


class Workspace:
    """A directory of drafts backed by a git repository."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.git = GitRepo(self.root)

    @classmethod
    def open(cls, root: Path | str | None = None) -> Workspace:
        """Open the workspace at ``root``, creating folder and repo on first use."""
        workspace = cls(Path(root) if root is not None else default_root())
        workspace.root.mkdir(parents=True, exist_ok=True)
        if not workspace.git.is_repo():
            workspace.git.init()
        workspace.git.ensure_identity()
        return workspace

    # ------------------------------------------------------------- file access

    def path_for(self, name: str) -> Path:
        """Absolute path of draft ``name`` (sanitized, always inside the root)."""
        return self.root / sanitize_name(name)

    def exists(self, name: str) -> bool:
        return self.path_for(name).is_file()

    def read(self, name: str) -> str:
        path = self.path_for(name)
        if not path.is_file():
            raise DraftNotFoundError(f"no draft called {display_name(path.name)!r}")
        return path.read_text(encoding="utf-8")

    def write(self, name: str, text: str) -> Path:
        """Write ``text`` atomically, so a crash never leaves a half-written file.

        The text goes to a temporary file first and is then renamed over the
        draft; ``os.replace`` is atomic on POSIX and Windows.
        """
        path = self.path_for(name)
        tmp = path.with_name(f".{path.name}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        return path

    def drafts(self) -> list[str]:
        """File names of all drafts in the workspace, sorted."""
        return sorted(p.name for p in self.root.iterdir() if p.is_file() and is_draft_file(p.name))

    # ------------------------------------------------------------- versioning

    def is_dirty(self, name: str) -> bool:
        """True if the draft on disk differs from its last commit."""
        return self.git.is_dirty(self.path_for(name).name)

    def commit(self, name: str, message: str) -> str | None:
        """Commit draft ``name`` if it changed; return the hash or ``None``."""
        return self.git.commit_paths([self.path_for(name).name], message)

    def commit_message(self, name: str, verb: str = "Edit") -> str:
        """Describe a change by its word delta, e.g. ``Edit essay.md (+120 words)``."""
        file_name = self.path_for(name).name
        before = self.committed_text(name)
        after = self.read(name) if self.exists(name) else ""
        if before is None:
            return f"Create {file_name} ({count_words(after)} words)"
        delta = count_words(after) - count_words(before)
        return f"{verb} {file_name} ({delta:+d} words)"

    def snapshot(self, name: str) -> str | None:
        """Commit changes made outside Drafts (another editor, a crash, autosaves)."""
        if not self.exists(name) or not self.is_dirty(name):
            return None
        return self.commit(name, self.commit_message(name, verb="Snapshot"))

    def committed_text(self, name: str, rev: str = "HEAD") -> str | None:
        """Text of the draft at ``rev`` or ``None`` if it was not committed there."""
        if not self.git.has_commits():
            return None
        return self.git.show(rev, self.path_for(name).name)

    def history(self, name: str, limit: int | None = None) -> list[Version]:
        """Committed versions of a draft, newest first, with word counts."""
        file_name = self.path_for(name).name
        commits = self.git.log([file_name], limit=limit)
        texts = self.git.cat_files([f"{c.sha}:{file_name}" for c in commits])
        parents = self.git.cat_files([f"{c.sha}^:{file_name}" for c in commits])
        versions = []
        for commit, text, parent in zip(commits, texts, parents, strict=True):
            words = count_words(text or "")
            versions.append(Version(commit, words, words - count_words(parent or "")))
        return versions

    def text_at(self, name: str, rev: str) -> str:
        """Text of the draft at revision ``rev`` (a hash, ``HEAD~2``, a tag...)."""
        file_name = self.path_for(name).name
        try:
            sha = self.git.resolve(rev)
        except GitError as exc:
            raise DraftNotFoundError(str(exc)) from None
        text = self.git.show(sha, file_name)
        if text is None:
            raise DraftNotFoundError(f"{display_name(file_name)!r} did not exist at {rev}")
        return text

    def restore(self, name: str, rev: str) -> str | None:
        """Bring back the version of ``name`` from ``rev`` as a *new* commit.

        History is never rewritten: the old text is written to the file and
        committed on top, so the version being replaced stays in history and
        the restore itself can be undone with another restore. Uncommitted
        edits are snapshotted first so they are never lost. Returns ``None``
        if the draft already matches that version.
        """
        old_text = self.text_at(name, rev)
        self.snapshot(name)
        short = self.git.resolve(rev)[:7]
        self.write(name, old_text)
        file_name = self.path_for(name).name
        return self.commit(name, f"{RESTORE_PREFIX}{file_name} to {short}")

    def list_drafts(self) -> list[DraftInfo]:
        """All drafts with word count, last-modified time and commit count.

        Commit counts come from a single ``git log`` pass over the repository
        instead of one git call per draft.
        """
        counts: dict[str, int] = {}
        for commit in self.git.log():
            for file_name in commit.files:
                counts[file_name] = counts.get(file_name, 0) + 1
        infos = []
        for file_name in self.drafts():
            path = self.root / file_name
            infos.append(
                DraftInfo(
                    file_name=file_name,
                    name=display_name(file_name),
                    words=count_words(path.read_text(encoding="utf-8", errors="replace")),
                    modified=datetime.fromtimestamp(path.stat().st_mtime),
                    commits=counts.get(file_name, 0),
                )
            )
        return sorted(infos, key=lambda info: info.modified, reverse=True)
