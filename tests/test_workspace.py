import subprocess
from pathlib import Path

import pytest

from drafts.gitrepo import FALLBACK_EMAIL, FALLBACK_NAME, GitRepo
from drafts.workspace import DraftNotFoundError, Workspace, default_root


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_open_creates_folder_and_repository(tmp_path: Path) -> None:
    root = tmp_path / "new" / "place"
    ws = Workspace.open(root)
    assert (root / ".git").is_dir()
    assert ws.git.current_branch() == "main"
    assert not ws.git.has_commits()
    Workspace.open(root)  # opening again is harmless
    assert ws.drafts() == []


def test_workspace_inside_another_repo_gets_its_own(tmp_path: Path) -> None:
    project = tmp_path / "project"
    GitRepo(project).init()
    ws = Workspace.open(project / "drafts")
    assert (ws.root / ".git").is_dir()
    ws.write("a", "words")
    ws.commit("a", "first")
    assert not GitRepo(project).has_commits()  # the outer repo was not touched


def test_identity_fallback_only_when_none_configured(tmp_path: Path, isolated_home: Path) -> None:
    ws = Workspace.open(tmp_path / "one")
    assert git(ws.root, "config", "--local", "user.name") == FALLBACK_NAME
    assert git(ws.root, "config", "--local", "user.email") == FALLBACK_EMAIL

    (isolated_home / ".gitconfig").write_text("[user]\n\tname = Ada\n\temail = ada@example.com\n")
    ws2 = Workspace.open(tmp_path / "two")
    local = subprocess.run(
        ["git", "-C", str(ws2.root), "config", "--local", "--get", "user.name"],
        capture_output=True,
        text=True,
    )
    assert local.stdout == ""  # nothing written locally: the global identity is used
    ws2.write("x", "hello")
    ws2.commit("x", "first")
    assert git(ws2.root, "log", "-1", "--format=%an") == "Ada"


def test_default_root_uses_env_then_home(isolated_home: Path) -> None:
    assert default_root({"DRAFTS_DIR": "/srv/words"}) == Path("/srv/words")
    assert default_root({}) == isolated_home / "drafts"


def test_commit_never_creates_empty_commits(ws: Workspace) -> None:
    ws.write("essay", "First line.")
    assert ws.commit("essay", "one") is not None
    assert ws.commit("essay", "two") is None  # nothing changed
    ws.write("essay", "First line.")  # same content written again
    assert ws.commit("essay", "three") is None
    assert len(ws.git.log()) == 1


def test_commit_only_includes_the_named_draft(ws: Workspace) -> None:
    ws.write("a", "alpha")
    ws.write("b", "beta")
    ws.commit("a", "only a")
    assert ws.git.log()[0].files == ("a.md",)
    assert ws.is_dirty("b")


def test_write_is_atomic_and_leaves_no_temp_file(ws: Workspace) -> None:
    ws.write("essay", "text ✍️\n")
    assert ws.read("essay") == "text ✍️\n"
    assert sorted(p.name for p in ws.root.iterdir()) == [".git", "essay.md"]


def test_history_and_restore_round_trip(ws: Workspace) -> None:
    ws.write("essay", "The first version.")
    v1 = ws.commit("essay", ws.commit_message("essay"))
    ws.write("essay", "The second, longer version of it.")
    v2 = ws.commit("essay", ws.commit_message("essay"))

    history = ws.history("essay")
    assert [v.commit.sha for v in history] == [v2, v1]
    assert [v.words for v in history] == [6, 3]
    assert [v.delta for v in history] == [3, 3]
    assert history[1].commit.subject == "Create essay.md (3 words)"

    v3 = ws.restore("essay", v1[:7])
    assert v3 is not None
    assert ws.read("essay") == "The first version."
    shas = [v.commit.sha for v in ws.history("essay")]
    assert shas == [v3, v2, v1]  # history only grew; nothing was rewritten
    assert ws.text_at("essay", v2) == "The second, longer version of it."
    assert ws.history("essay")[0].commit.subject == f"Restore essay.md to {v1[:7]}"


def test_restore_keeps_uncommitted_edits_in_history(ws: Workspace) -> None:
    ws.write("essay", "committed")
    v1 = ws.commit("essay", "v1")
    ws.write("essay", "precious unsaved paragraph")
    ws.restore("essay", v1)
    subjects = [v.commit.subject for v in ws.history("essay")]
    assert subjects[1].startswith("Snapshot essay.md")
    assert ws.text_at("essay", "HEAD~1") == "precious unsaved paragraph"


def test_restore_to_identical_version_makes_no_commit(ws: Workspace) -> None:
    ws.write("essay", "same")
    v1 = ws.commit("essay", "v1")
    assert ws.restore("essay", v1) is None
    assert len(ws.git.log()) == 1


def test_text_at_errors(ws: Workspace) -> None:
    ws.write("a", "alpha")
    first = ws.commit("a", "a")
    ws.write("b", "beta")
    ws.commit("b", "b")
    with pytest.raises(DraftNotFoundError, match="unknown revision"):
        ws.text_at("a", "no-such-rev")
    with pytest.raises(DraftNotFoundError, match="did not exist"):
        ws.text_at("b", first)
    with pytest.raises(DraftNotFoundError):
        ws.read("missing")


def test_list_drafts_reports_words_and_commits(ws: Workspace) -> None:
    ws.write("essay", "one two three")
    ws.commit("essay", "1")
    ws.write("essay", "one two three four")
    ws.commit("essay", "2")
    ws.write("notes.txt", "loose notes")
    (ws.root / "image.png").write_bytes(b"\x89PNG")
    (ws.root / ".hidden.md").write_text("secret")

    infos = {info.name: info for info in ws.list_drafts()}
    assert set(infos) == {"essay", "notes.txt"}
    assert infos["essay"].words == 4 and infos["essay"].commits == 2
    assert infos["notes.txt"].words == 2 and infos["notes.txt"].commits == 0


def test_cat_files_batch_reads_many_versions_and_missing(ws: Workspace) -> None:
    ws.write("a", "line one\n")
    first = ws.commit("a", "1")
    ws.write("a", "line one\nline two ünïcode\n")
    second = ws.commit("a", "2")
    texts = ws.git.cat_files([f"{first}:a.md", f"{second}:a.md", f"{first}^:a.md", "HEAD:nope"])
    assert texts == ["line one\n", "line one\nline two ünïcode\n", None, None]
