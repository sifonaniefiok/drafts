"""Shared fixtures.

Every test runs with a fresh, empty HOME and no global or system git config,
so the tests behave the same on a developer laptop and in CI, and never read or
modify the real user's git settings or ~/drafts.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from drafts.workspace import Workspace

GIT_ENV_VARS = (
    "DRAFTS_DIR",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("COLUMNS", "120")
    for var in GIT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return home


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path / "drafts")


class FakeClock:
    """A monotonic clock the test moves forward by hand."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def commit_on(monkeypatch: pytest.MonkeyPatch) -> Callable[[Workspace, str, str, str], str | None]:
    """Write a draft and commit it with a fixed date: ``commit_on(ws, name, text, when)``.

    git reads GIT_AUTHOR_DATE / GIT_COMMITTER_DATE from the environment, which
    lets tests create history "in the past" without touching the clock.
    """

    def commit(ws: Workspace, name: str, text: str, when: str) -> str | None:
        monkeypatch.setenv("GIT_AUTHOR_DATE", when)
        monkeypatch.setenv("GIT_COMMITTER_DATE", when)
        ws.write(name, text)
        return ws.commit(name, ws.commit_message(name))

    return commit
