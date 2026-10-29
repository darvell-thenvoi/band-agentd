import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def make_repo(path: Path, *, commit: bool = True) -> Path:
    path.mkdir()
    git(path, "init", "-q")
    (path / "sub").mkdir()
    (path / "sub" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (path / "README.md").write_text("repo\n", encoding="utf-8")
    if commit:
        git(path, "add", ".")
        git(path, "commit", "-q", "-m", "init")
    return path
