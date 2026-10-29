from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from band.workspaces import RoomWorkspaces

logger = logging.getLogger(__name__)

WorkspaceResolver = Callable[[str], str]

BRANCH_PREFIX = "band/"


class WorkspaceMode(StrEnum):
    SHARED = "shared"
    WORKTREE = "worktree"


class SharedWorkspace(RoomWorkspaces):
    """Give every room the same working directory.

    The Codex adapter otherwise claims one directory per room and refuses a
    second room in the same place. In shared mode an agent works in the folder
    its operator chose, so concurrent rooms share it, as they would share a
    terminal session opened there.
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._shared = str(path.resolve())
        self._rooms: set[str] = set()

    @property
    def rooms(self) -> tuple[str, ...]:
        return tuple(self._rooms)

    def workspace(self, room_id: str) -> str:
        return self._shared

    def claim(self, room_id: str, workspace: str | None = None) -> str:
        self._rooms.add(room_id)
        return self._shared

    def release(self, room_id: str, workspace: str | None = None) -> None:
        self._rooms.discard(room_id)


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def worktree_repo(cwd: Path) -> Path:
    """The top of the git repository containing ``cwd``, ready for worktrees.

    Raises ValueError naming the fix when worktrees cannot be made there.
    """
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        if "dubious ownership" in top.stderr:
            raise ValueError(
                f"git refuses {cwd} because another user owns it. Run the agent as "
                f"the owner, or run: git config --global --add safe.directory {cwd}"
            )
        raise ValueError(
            f"Worktree mode needs a git repository, and {cwd} is not in one. "
            "Use workspace: shared instead."
        )
    repo = Path(top.stdout.strip()).resolve()
    if _git(repo, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
        raise ValueError(
            f"Worktree mode needs at least one commit in {repo}. Commit something first."
        )
    return repo


def worktree_root(repo: Path) -> Path:
    digest = hashlib.sha1(str(repo).encode("utf-8")).hexdigest()[:8]
    return data_home() / "band-agentd" / "worktrees" / f"{repo.name}-{digest}"


def git_worktree_resolver(
    repo: Path, root: Path, subdir: Path = Path(".")
) -> WorkspaceResolver:
    """Give each room its own worktree of ``repo`` on branch ``band/<room-id>``.

    ``subdir`` places the room inside the same subdirectory the operator chose.
    """
    root = root.resolve()

    def resolve(room_id: str) -> str:
        path = (root / room_id).resolve()
        if root not in path.parents:
            raise ValueError("room id cannot escape the worktree root")
        workspace = path / subdir
        if (path / ".git").exists():
            return str(workspace)

        root.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "prune")
        branch = f"{BRANCH_PREFIX}{room_id}"
        branch_exists = (
            _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
        )
        args = ["worktree", "add", str(path)]
        args += [branch] if branch_exists else ["-b", branch]
        result = _git(repo, *args)
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed for room {room_id}: {result.stderr.strip()}"
            )
        logger.info("Room %s works in %s on branch %s", room_id, workspace, branch)
        return str(workspace)

    return resolve


def room_worktree_resolver(cwd: Path) -> WorkspaceResolver:
    repo = worktree_repo(cwd)
    subdir = cwd.resolve().relative_to(repo)
    return git_worktree_resolver(repo, worktree_root(repo), subdir)
