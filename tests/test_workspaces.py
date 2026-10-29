import subprocess
from pathlib import Path

import pytest
from gitrepo import git, make_repo

from band_agentd.workspaces import SharedWorkspace, room_worktree_resolver


def test_shared_workspace_gives_every_room_the_same_folder(tmp_path):
    shared = SharedWorkspace(tmp_path)

    with shared.claiming("room-1") as first:
        second = shared.claim("room-2")

    assert first == second == str(tmp_path.resolve())
    assert set(shared.rooms) == {"room-1", "room-2"}
    shared.release("room-1")
    assert shared.rooms == ("room-2",)


def test_git_repo_gets_a_worktree_per_room_on_its_own_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = make_repo(tmp_path / "repo")
    resolve = room_worktree_resolver(repo)

    first = Path(resolve("room-1"))
    second = Path(resolve("room-2"))

    assert (first / "README.md").read_text(encoding="utf-8") == "repo\n"
    assert first != second
    assert git(first, "branch", "--show-current") == "band/room-1"
    assert git(second, "branch", "--show-current") == "band/room-2"
    assert repo not in first.parents
    assert resolve("room-1") == str(first)


def test_worktree_is_recreated_from_the_existing_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = make_repo(tmp_path / "repo")
    resolve = room_worktree_resolver(repo)
    workspace = Path(resolve("room-1"))
    (workspace / "note.txt").write_text("work\n", encoding="utf-8")
    git(workspace, "add", "note.txt")
    git(workspace, "commit", "-q", "-m", "room work")
    subprocess.run(["rm", "-rf", str(workspace)], check=True)

    restored = Path(resolve("room-1"))

    assert (restored / "note.txt").read_text(encoding="utf-8") == "work\n"


def test_subdirectory_of_a_repo_maps_to_the_same_subdirectory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = make_repo(tmp_path / "repo")

    workspace = Path(room_worktree_resolver(repo / "sub")("room-1"))

    assert workspace.name == "sub"
    assert (workspace / "app.py").is_file()


def test_worktree_mode_rejects_a_plain_folder(tmp_path):
    with pytest.raises(ValueError, match="needs a git repository"):
        room_worktree_resolver(tmp_path)


def test_worktree_mode_rejects_a_repo_without_commits(tmp_path):
    repo = make_repo(tmp_path / "repo", commit=False)

    with pytest.raises(ValueError, match="at least one commit"):
        room_worktree_resolver(repo)
