from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import sys
from enum import StrEnum
from pathlib import Path

SYSTEM_UNIT_DIR = Path("/etc/systemd/system")


class ServiceScope(StrEnum):
    USER = "user"
    SYSTEM = "system"


def default_scope() -> ServiceScope:
    return ServiceScope.SYSTEM if os.geteuid() == 0 else ServiceScope.USER


def unit_path(unit_name: str, scope: ServiceScope) -> Path:
    if scope is ServiceScope.SYSTEM:
        return SYSTEM_UNIT_DIR / f"{unit_name}.service"
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "systemd" / "user" / f"{unit_name}.service"


def _unit_value(value: str) -> str:
    """Escape a value for a quoted unit-file setting; systemd expands % specifiers."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def render_systemd_unit(
    config_path: str | Path,
    *,
    unit_name: str = "band-agentd",
    scope: ServiceScope = ServiceScope.USER,
) -> str:
    config = Path(config_path).expanduser().resolve()
    # systemd starts services with a minimal PATH and, for root units, no HOME.
    # Codex and Claude live on the installing shell's PATH and keep their logins
    # under HOME, so both are captured from the installing session.
    lines = [
        "[Unit]",
        f"Description=Band agent daemon ({unit_name})",
    ]
    if scope is ServiceScope.SYSTEM:
        lines += ["After=network-online.target", "Wants=network-online.target"]
    lines += [
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={config.parent}",
        f'ExecStart="{sys.executable}" -m band_agentd run --config "{config}"',
        f'Environment="PATH={_unit_value(os.environ.get("PATH", ""))}"',
        f'Environment="HOME={_unit_value(str(Path.home()))}"',
        "Environment=PYTHONUNBUFFERED=1",
        "Restart=always",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=" + ("multi-user.target" if scope is ServiceScope.SYSTEM else "default.target"),
        "",
    ]
    return "\n".join(lines)


def _systemctl(scope: ServiceScope, *args: str) -> subprocess.CompletedProcess[str]:
    command = ["systemctl"]
    if scope is ServiceScope.USER:
        command.append("--user")
    return subprocess.run([*command, *args], capture_output=True, text=True)


def _require_ok(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"systemctl {action} failed: {detail}")


def _ensure_linger() -> str | None:
    """Keep user services running after the SSH session ends.

    Returns a warning when lingering cannot be enabled without root.
    """
    user = pwd.getpwuid(os.getuid()).pw_name
    shown = subprocess.run(
        ["loginctl", "show-user", user, "-p", "Linger", "--value"],
        capture_output=True,
        text=True,
    )
    if shown.stdout.strip() == "yes":
        return None
    enabled = subprocess.run(
        ["loginctl", "enable-linger", user], capture_output=True, text=True
    )
    if enabled.returncode == 0:
        return None
    return (
        "The service stops when you log out until lingering is enabled. "
        f"Run once as an administrator: sudo loginctl enable-linger {user}"
    )


def require_systemd() -> None:
    if shutil.which("systemctl") is None:
        raise RuntimeError(
            "systemd is not available on this machine. Rerun install with "
            "--service none and start the daemon with `band-agentd run`."
        )


def install_systemd_service(
    config_path: str | Path,
    *,
    unit_name: str,
    scope: ServiceScope,
) -> tuple[Path, str | None]:
    require_systemd()

    path = unit_path(unit_name, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_systemd_unit(config_path, unit_name=unit_name, scope=scope),
        encoding="utf-8",
    )
    os.chmod(path, 0o644)

    warning = _ensure_linger() if scope is ServiceScope.USER else None
    service = f"{unit_name}.service"
    _require_ok(_systemctl(scope, "daemon-reload"), "daemon-reload")
    _require_ok(_systemctl(scope, "enable", service), "enable")
    _require_ok(_systemctl(scope, "restart", service), "restart")
    return path, warning


def remove_systemd_service(unit_name: str, scope: ServiceScope) -> Path | None:
    """Stop and disable the agent's service and delete its unit file.

    Returns the deleted unit file, or None when there was none.
    """
    path = unit_path(unit_name, scope)
    has_systemd = shutil.which("systemctl") is not None
    if has_systemd:
        # A unit that was never loaded makes this fail harmlessly.
        _systemctl(scope, "disable", "--now", f"{unit_name}.service")
    if not path.exists():
        return None
    path.unlink()
    if has_systemd:
        _require_ok(_systemctl(scope, "daemon-reload"), "daemon-reload")
    return path
