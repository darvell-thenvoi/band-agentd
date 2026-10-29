from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

WorkspaceResolver = Callable[[str], str]

BRANCH_PREFIX = "band/"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def is_git_worktree(path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def worktree_root(repo: Path) -> Path:
    digest = hashlib.sha1(str(repo).encode("utf-8")).hexdigest()[:8]
    return data_home() / "band-agentd" / "worktrees" / f"{repo.name}-{digest}"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def git_worktree_resolver(
    repo: Path, root: Path, subdir: Path = Path(".")
) -> WorkspaceResolver:
    """Give each room its own worktree of ``repo`` on branch ``band/<room-id>``.

    Rooms run concurrently, so they cannot share one checkout. A worktree keeps
    the repository's history and remotes while isolating each room's edits.
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


def room_workspace_resolver(cwd: Path) -> WorkspaceResolver:
    if is_git_worktree(cwd):
        top = _git(cwd, "rev-parse", "--show-toplevel").stdout.strip()
        repo = Path(top).resolve()
        subdir = cwd.resolve().relative_to(repo)
        return git_worktree_resolver(repo, worktree_root(repo), subdir)

    from band import create_room_workspace_resolver

    return create_room_workspace_resolver(cwd)
