"""A deliberately small wrapper around the ``git`` command-line tool.

Why shell out instead of using a library such as GitPython?

* ``git`` is already installed wherever someone wants version-controlled text,
  so there is no extra dependency to install or keep in sync;
* the commands below are exactly what you would type yourself, which makes the
  behaviour easy to reason about and to reproduce by hand when debugging.

Every call goes through :meth:`GitRepo.run`, which always passes ``-C <root>``
(so the current directory never matters), disables the pager and terminal
prompts, and raises :class:`GitError` with git's own message on failure.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: Identity used only when the user has no git identity configured at all, so
#: that commits never fail on a fresh machine. It is written to the workspace
#: repository's *local* config and never to the user's global config.
FALLBACK_NAME = "Drafts"
FALLBACK_EMAIL = "drafts@localhost"

_FIELD = "\x1f"  # ASCII unit separator: cannot appear in hashes, dates or one-line subjects.
_RECORD = "\x1e"  # ASCII record separator: marks the start of each commit in log output.


class GitError(RuntimeError):
    """A git command failed. The message contains git's stderr."""


@dataclass(frozen=True)
class Commit:
    """One entry from ``git log``."""

    sha: str
    short_sha: str
    date: datetime  # author date, with the timezone it was recorded in
    subject: str
    files: tuple[str, ...] = ()


class GitRepo:
    """Run git commands against the repository rooted at ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ basics

    def run(
        self,
        *args: str,
        input: str | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``git -C <root> <args>`` and return the completed process.

        Output is captured as UTF-8 text. ``core.quotepath=false`` keeps
        non-ASCII file names readable instead of octal-escaped.
        """
        full_env = dict(os.environ)
        full_env["GIT_TERMINAL_PROMPT"] = "0"  # never hang waiting for a password
        full_env["GIT_PAGER"] = "cat"
        if env:
            full_env.update(env)
        cmd = ["git", "-C", str(self.root), "-c", "core.quotepath=false", *args]
        result = subprocess.run(
            cmd,
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=full_env,
        )
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise GitError(f"git {' '.join(args)} failed: {message}")
        return result

    def is_repo(self) -> bool:
        """True if ``root`` itself holds a repository.

        We check for ``root/.git`` rather than asking git, because git would
        happily report a *parent* repository (e.g. if the workspace lives
        inside a code project) and we must not commit drafts into that.
        """
        return (self.root / ".git").exists()

    def init(self) -> None:
        """Create the repository with ``main`` as its first branch.

        ``symbolic-ref`` is used instead of ``git init -b main`` so this also
        works with git versions older than 2.28.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        self.run("init", "--quiet")
        self.run("symbolic-ref", "HEAD", "refs/heads/main")

    def ensure_identity(self) -> None:
        """Make sure commits have an author, without touching global config.

        ``git config user.name`` reads every config level (system, global,
        local), so the fallback is only written when nothing is configured.
        """
        for key, fallback in (("user.name", FALLBACK_NAME), ("user.email", FALLBACK_EMAIL)):
            if not self.run("config", key, check=False).stdout.strip():
                self.run("config", "--local", key, fallback)

    def has_commits(self) -> bool:
        return self.run("rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0

    def resolve(self, rev: str) -> str:
        """Full commit hash for ``rev`` (raises :class:`GitError` if unknown)."""
        out = self.run("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
        if out.returncode != 0:
            raise GitError(f"unknown revision: {rev}")
        return out.stdout.strip()

    # ---------------------------------------------------------------- changes

    def is_dirty(self, path: str) -> bool:
        """True if ``path`` differs from the last commit (or is untracked)."""
        return bool(self.run("status", "--porcelain", "--", path).stdout.strip())

    def commit_paths(
        self,
        paths: Sequence[str],
        message: str,
        env: Mapping[str, str] | None = None,
    ) -> str | None:
        """Commit the current contents of ``paths`` and return the new hash.

        Only the given paths are committed, even if other files changed. If
        nothing changed, no commit is created and ``None`` is returned: Drafts
        never makes empty commits.
        """
        if not paths:
            return None
        self.run("add", "--all", "--", *paths)
        staged = self.run("diff", "--cached", "--quiet", "--", *paths, check=False)
        if staged.returncode == 0:
            return None
        self.run("commit", "--quiet", "--no-verify", "-m", message, "--", *paths, env=env)
        return self.run("rev-parse", "HEAD").stdout.strip()

    # ---------------------------------------------------------------- history

    def log(self, paths: Iterable[str] = (), *, limit: int | None = None) -> list[Commit]:
        """Commits touching ``paths`` (all commits if empty), newest first."""
        if not self.has_commits():
            return []
        fmt = _RECORD + _FIELD.join(["%H", "%h", "%aI", "%s"])
        args = ["log", f"--format={fmt}", "--name-only", "--no-renames"]
        if limit is not None:
            args.append(f"--max-count={limit}")
        args += ["--", *paths]
        commits: list[Commit] = []
        for record in self.run(*args).stdout.split(_RECORD)[1:]:
            header, _, file_block = record.partition("\n")
            sha, short, date, subject = header.split(_FIELD, 3)
            files = tuple(line for line in file_block.splitlines() if line.strip())
            commits.append(Commit(sha, short, datetime.fromisoformat(date), subject, files))
        return commits

    def show(self, rev: str, path: str) -> str | None:
        """Contents of ``path`` at ``rev``, or ``None`` if it did not exist there."""
        return self.cat_files([f"{rev}:{path}"])[0]

    def cat_files(self, specs: Sequence[str]) -> list[str | None]:
        """Read many ``rev:path`` blobs with a single ``git cat-file --batch``.

        Computing statistics needs the text of every draft at every commit.
        Starting one ``git show`` process per blob would be slow, so all
        requests are sent on stdin and the replies parsed from one stream.
        Missing objects (a file that did not exist yet, or the parent of the
        first commit) come back as ``None``.
        """
        if not specs:
            return []
        proc = subprocess.run(
            ["git", "-C", str(self.root), "cat-file", "--batch"],
            input="".join(f"{spec}\n" for spec in specs).encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise GitError(f"git cat-file failed: {proc.stderr.decode(errors='replace')}")
        data = proc.stdout
        results: list[str | None] = []
        pos = 0
        for _ in specs:
            newline = data.index(b"\n", pos)
            header = data[pos:newline].decode("utf-8", errors="replace").split()
            pos = newline + 1
            if len(header) == 3 and header[2].isdigit():
                size = int(header[2])
                results.append(data[pos : pos + size].decode("utf-8", errors="replace"))
                pos += size + 1  # skip the content and its trailing newline
            else:  # "<spec> missing" or "<spec> ambiguous"
                results.append(None)
        return results

    # ---------------------------------------------------------------- remotes

    def remotes(self) -> list[str]:
        return self.run("remote").stdout.split()

    def current_branch(self) -> str:
        return self.run("symbolic-ref", "--short", "HEAD").stdout.strip()
