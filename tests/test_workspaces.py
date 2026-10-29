import subprocess
from pathlib import Path

from band_agentd.workspaces import room_workspace_resolver


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def make_repo(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-q")
    (path / "sub").mkdir()
    (path / "sub" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (path / "README.md").write_text("repo\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "init")
    return path


def test_git_repo_gets_a_worktree_per_room_on_its_own_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = make_repo(tmp_path / "repo")
    resolve = room_workspace_resolver(repo)

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
    resolve = room_workspace_resolver(repo)
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

    workspace = Path(room_workspace_resolver(repo / "sub")("room-1"))

    assert workspace.name == "sub"
    assert (workspace / "app.py").is_file()


def test_plain_directory_gets_a_room_subdirectory(tmp_path):
    workspace = Path(room_workspace_resolver(tmp_path)("room-1"))

    assert workspace.parent == tmp_path.resolve()
    assert workspace.is_dir()
