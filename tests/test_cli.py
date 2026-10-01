"""End-to-end tests of the command line, calling ``main(argv)`` in-process."""

import subprocess
from datetime import date
from pathlib import Path

import pytest

from drafts import cli
from drafts.workspace import Workspace


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "words"


def run(root: Path, *argv: str) -> int:
    return cli.main(["--dir", str(root), *argv])


def test_new_list_and_history(root: Path, capsys) -> None:
    assert run(root, "new", "My Essay") == 0
    assert (root / "My-Essay.md").exists()
    assert run(root, "new", "My Essay") == 1  # refuses to overwrite
    (root / "My-Essay.md").write_text("Some words here.")
    assert run(root, "snapshot") == 0
    capsys.readouterr()

    assert run(root, "list") == 0
    out = capsys.readouterr().out
    assert "My-Essay" in out and "Words" in out and "Commits" in out
    assert "│        3 │" in out or " 3 " in out

    assert run(root, "history", "My Essay") == 0
    out = capsys.readouterr().out
    assert "Create (0 words)" in out
    assert "Snapshot (+3 words)" in out


def test_list_empty_workspace(root: Path, capsys) -> None:
    assert run(root, "list") == 0
    assert "No drafts yet" in capsys.readouterr().out


def test_diff_defaults_and_explicit_revision(root: Path, capsys) -> None:
    ws = Workspace.open(root)
    ws.write("essay", "Attention is rare.")
    first = ws.commit("essay", "v1")
    ws.write("essay", "Attention is rare and generous.")
    ws.commit("essay", "v2")

    # No uncommitted changes: shows what the last commit changed.
    assert run(root, "diff", "essay") == 0
    out = capsys.readouterr().out
    assert "{+rare and generous.+}" in out and "[-rare.-]" in out
    assert "+3 words" in out and "-1 words" in out

    # Uncommitted changes: shows them against the last commit.
    ws.write("essay", "Attention is rare and generous. Always.")
    assert run(root, "diff", "essay") == 0
    out = capsys.readouterr().out
    assert "{+Always.+}" in out and "[-" not in out

    assert run(root, "diff", "essay", first[:7], "--lines") == 0
    out = capsys.readouterr().out
    assert f"--- {first[:7]}" in out
    assert "-Attention is rare." in out
    assert "+Attention is rare and generous. Always." in out


def test_restore_command_adds_a_commit(root: Path, capsys) -> None:
    ws = Workspace.open(root)
    ws.write("essay", "old text")
    first = ws.commit("essay", "v1")
    ws.write("essay", "new text")
    ws.commit("essay", "v2")
    assert run(root, "restore", "essay", first[:7]) == 0
    assert "as new commit" in capsys.readouterr().out
    assert ws.read("essay") == "old text"
    assert len(ws.git.log()) == 3
    assert run(root, "restore", "essay", "nope") == 1
    assert "unknown revision" in capsys.readouterr().err


def test_stats_command_with_pinned_today(root: Path, capsys, monkeypatch, commit_on) -> None:
    ws = Workspace.open(root)
    commit_on(ws, "essay", "one two three", "2026-03-09T10:00:00+00:00")
    commit_on(ws, "essay", "one two three four", "2026-03-10T10:00:00+00:00")
    monkeypatch.setattr(cli, "today", lambda: date(2026, 3, 10))
    assert run(root, "stats") == 0
    out = capsys.readouterr().out
    assert "4 words in total" in out
    assert "1 written today" in out
    assert "streak 2 days" in out
    # 14 days ending on 10 March: 25 February to 10 March.
    assert "Wed 25 Feb" in out and "Mon 09 Mar" in out and "Tue 10 Mar" in out
    assert "Tue 24 Feb" not in out


def test_export_html_to_file_and_txt_to_stdout(root: Path, tmp_path: Path, capsys) -> None:
    ws = Workspace.open(root)
    ws.write("essay", "# Title\n\nHello *world* <b>.")
    target = tmp_path / "essay.html"
    assert run(root, "export", "essay", "--format", "html", "-o", str(target)) == 0
    html = target.read_text()
    assert "<h1>Title</h1>" in html and "<em>world</em>" in html and "&lt;b&gt;" in html

    capsys.readouterr()
    assert run(root, "export", "essay", "--format", "txt") == 0
    out = capsys.readouterr().out
    assert "Title" in out and "Hello world" in out and "#" not in out


def test_invalid_names_and_missing_drafts_fail_cleanly(root: Path, capsys) -> None:
    assert run(root, "new", "../../etc/passwd") == 1
    assert "path separators" in capsys.readouterr().err
    assert run(root, "export", "ghost") == 1
    assert "no draft called 'ghost'" in capsys.readouterr().err
    assert run(root, "history", "ghost") == 1


def test_dir_option_position_and_env_var(tmp_path: Path, monkeypatch, capsys) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    assert cli.main(["new", "x", "--dir", str(a)]) == 0
    assert (a / "x.md").exists()
    monkeypatch.setenv("DRAFTS_DIR", str(b))
    assert cli.main(["new", "y"]) == 0
    assert (b / "y.md").exists()


def test_default_workspace_is_in_home(isolated_home: Path) -> None:
    assert cli.main(["new", "z"]) == 0
    assert (isolated_home / "drafts" / "z.md").exists()


def test_numeric_options_must_be_positive(root: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(root, "write", "essay", "--width", "0")
    assert exit_info.value.code == 2


def test_write_refuses_without_a_terminal(root: Path, capsys) -> None:
    # Under pytest stdin/stdout are not TTYs.
    assert run(root, "write", "essay") == 1
    assert "interactive terminal" in capsys.readouterr().out


def test_sync_without_remote_explains_how(root: Path, capsys) -> None:
    assert run(root, "sync") == 1
    assert "No remote configured" in capsys.readouterr().out


def test_sync_pushes_to_a_local_bare_remote(root: Path, tmp_path: Path, capsys) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    ws = Workspace.open(root)
    ws.git.run("remote", "add", "origin", str(remote))
    ws.write("essay", "pushed words")  # uncommitted: sync snapshots it first
    assert run(root, "sync") == 0
    log = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--format=%s", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Create essay.md (2 words)" in log
    ws.write("essay", "pushed words again")
    assert run(root, "sync") == 0  # second sync: fetch + pull --rebase + push
