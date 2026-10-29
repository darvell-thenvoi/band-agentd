from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import stat
import sys
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from .config import DaemonConfig
from .daemon import AgentDaemon
from .runtimes import check_runtime, format_models, list_models, validate_choice
from .service import (
    ServiceScope,
    default_scope,
    install_systemd_service,
    remove_systemd_service,
    render_systemd_unit,
)

DEFAULT_UNIT = "band-agentd"
ADAPTERS = ("codex", "claude")
USER_KEY_PREFIXES = ("thnv_u_", "band_u_")


class ServiceMode(StrEnum):
    SYSTEMD = "systemd"
    NONE = "none"


class Access(StrEnum):
    FULL = "full"
    ASK = "ask"
    READ_ONLY = "read-only"


# How much the agent may do, as settings for both runtimes; each runtime
# ignores the fields that belong to the other.
ACCESS_SETTINGS: dict[Access, dict[str, Any]] = {
    Access.FULL: {"yolo": True},
    Access.ASK: {"yolo": False, "approval_mode": "manual"},
    Access.READ_ONLY: {
        "yolo": False,
        "approval_mode": "auto_decline",
        "sandbox": "read-only",
        "permission_mode": "plan",
    },
}


def default_config_path(unit: str = DEFAULT_UNIT) -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "band-agentd" / f"{unit}.yaml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="band-agentd")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser(
        "install", help="write the agent config and start it as a service"
    )
    install.add_argument("--adapter", choices=ADAPTERS)
    install.add_argument("--cwd", type=Path, help="repository or directory the agent works in")
    install.add_argument("--agent-id", help="ID shown by Band after Connect Agent")
    install.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="read the agent API key from the first line of stdin",
    )
    install.add_argument(
        "--access",
        choices=[level.value for level in Access],
        default=Access.ASK,
        help="full: no prompts; ask: approvals in the room; read-only: no changes",
    )
    install.add_argument("--name", default="Band coding agent")
    install.add_argument("--description", default="A coding agent that works in Band rooms.")
    install.add_argument("--instructions", help="extra system-prompt text, such as the agent's role")
    install.add_argument("--model", help="model id from `band-agentd models`")
    install.add_argument("--reasoning-effort", help="reasoning level from `band-agentd models`")
    install.add_argument("--unit", default=DEFAULT_UNIT)
    install.add_argument("--config", type=Path)
    install.add_argument(
        "--service", choices=[mode.value for mode in ServiceMode], default=ServiceMode.SYSTEMD
    )
    install.add_argument("--skip-checks", action="store_true")
    install.add_argument("--force", action="store_true")

    run = subparsers.add_parser("run", help="run and supervise the configured agent")
    run.add_argument("--config", type=Path, default=default_config_path())

    models = subparsers.add_parser(
        "models", help="list the models and reasoning levels this machine's login offers"
    )
    models.add_argument("--adapter", choices=ADAPTERS, required=True)
    models.add_argument("--json", action="store_true")

    init = subparsers.add_parser("init", help="write a starter config without credentials")
    init.add_argument("--config", type=Path, default=default_config_path())
    init.add_argument("--name", default="Band coding agent")
    init.add_argument("--description", default="A coding agent that works in Band rooms.")
    init.add_argument("--adapter", choices=ADAPTERS, default="codex")
    init.add_argument("--cwd", default=".", type=Path)
    init.add_argument("--access", choices=[level.value for level in Access], default=Access.ASK)
    init.add_argument("--force", action="store_true")

    remove = subparsers.add_parser(
        "remove", help="stop an agent's service and delete its service file and settings"
    )
    remove.add_argument("unit", help="service name, the settings file name without .yaml")

    systemd = subparsers.add_parser("systemd", help="print the unit install would write")
    systemd.add_argument("--config", type=Path, default=default_config_path())
    systemd.add_argument("--unit", default=DEFAULT_UNIT)

    return parser


def _starter_config(args: argparse.Namespace) -> dict[str, Any]:
    runtime = {
        "adapter": args.adapter,
        "cwd": str(Path(args.cwd).expanduser().resolve()),
        "yolo": False,
        "instructions": None,
        "instructions_file": None,
        "model": None,
        "reasoning_effort": None,
        "approval_mode": "manual",
        "sandbox": None,
        "permission_mode": "acceptEdits",
        "max_thinking_tokens": None,
        "emit_tool_calls": True,
        "emit_thoughts": True,
        "emit_tasks": True,
        "emit_usage": True,
    }
    runtime.update(ACCESS_SETTINGS[Access(args.access)])
    return {
        "agent": {
            "id": None,
            "api_key": None,
            "name": args.name,
            "description": args.description,
        },
        "runtime": runtime,
        "restart": {
            "enabled": True,
            "initial_delay_s": 2,
            "max_delay_s": 60,
        },
        "shutdown_timeout_s": 30,
        "reload_interval_s": 1,
    }


def _write_config(path: Path, data: dict[str, Any], *, force: bool) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and not force:
        raise FileExistsError(f"Config already exists: {path} (use --force to replace it)")
    path.parent.mkdir(mode=stat.S_IRWXU, parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def _interactive() -> bool:
    return sys.stdin.isatty()


def _value(current: str | None, label: str, flag: str, default: str | None = None) -> str:
    if current:
        return current
    if not _interactive():
        raise ValueError(f"{flag} is required when no terminal is attached")
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip() or (default or "")
    if not answer:
        raise ValueError(f"{label} is required")
    return answer


def _api_key(from_stdin: bool) -> str:
    if from_stdin:
        key = sys.stdin.readline().strip()
    elif _interactive():
        key = getpass.getpass("Agent API key: ").strip()
    else:
        raise ValueError("Pass the agent API key on stdin with --api-key-stdin")

    if not key:
        raise ValueError("The agent API key is empty")
    if key.startswith(USER_KEY_PREFIXES):
        raise ValueError(
            "That is a user API key. Use the API Key shown after Connect Agent "
            "on https://app.band.ai/agents/create"
        )
    return key


def _agent_id(value: str) -> str:
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError as exc:
        raise ValueError(
            "The agent ID must be the UUID shown after Connect Agent, "
            "not the name or handle"
        ) from exc


async def _fetch_agent(agent_id: str, api_key: str) -> tuple[str, str]:
    import httpx
    from band.client.rest import (
        DEFAULT_REQUEST_OPTIONS,
        AsyncRestClient,
        UnauthorizedError,
        aclose_rest_client,
    )
    from band.config.settings import PlatformSettings
    from band_rest.core.api_error import ApiError

    client = AsyncRestClient(
        api_key=api_key, base_url=PlatformSettings().BAND_REST_URL.rstrip("/")
    )
    try:
        response = await client.agent_api_identity.get_agent_me(
            request_options=DEFAULT_REQUEST_OPTIONS
        )
    except UnauthorizedError as exc:
        raise RuntimeError(
            "Band rejected the agent API key. Copy the API Key again, or generate a "
            "new one from the agent's menu on app.band.ai."
        ) from exc
    except ApiError as exc:
        raise RuntimeError(f"Band could not verify the agent (HTTP {exc.status_code}).") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach Band to verify the agent: {exc}") from exc
    finally:
        await aclose_rest_client(client)

    agent = response.data
    if agent.id != agent_id:
        raise RuntimeError(
            f"This API key belongs to agent {agent.id}, not {agent_id}. "
            "Use the ID and API Key from the same Connect Agent result."
        )
    return agent.name, agent.handle or ""


def _install(args: argparse.Namespace) -> None:
    adapter = _value(args.adapter, "Agent type (codex or claude)", "--adapter", "codex")
    if adapter not in ADAPTERS:
        raise ValueError("Agent type must be codex or claude")

    cwd = Path(_value(str(args.cwd) if args.cwd else None, "Working directory", "--cwd"))
    cwd = cwd.expanduser().resolve()
    if not cwd.is_dir():
        raise ValueError(f"Working directory does not exist: {cwd}")

    agent_id = _agent_id(_value(args.agent_id, "Agent ID", "--agent-id"))
    api_key = _api_key(args.api_key_stdin)

    if not args.skip_checks:
        check_runtime(adapter)
        if args.model or args.reasoning_effort:
            models = asyncio.run(list_models(adapter))
            validate_choice(models, args.model, args.reasoning_effort)
        name, handle = asyncio.run(_fetch_agent(agent_id, api_key))
        print(f"Band accepted the credentials for {name} {handle}".rstrip())

    data = _starter_config(
        argparse.Namespace(
            adapter=adapter,
            name=args.name,
            description=args.description,
            cwd=cwd,
            access=args.access,
        )
    )
    data["agent"]["id"] = agent_id
    data["agent"]["api_key"] = api_key
    data["runtime"]["instructions"] = args.instructions
    data["runtime"]["model"] = args.model
    data["runtime"]["reasoning_effort"] = args.reasoning_effort
    DaemonConfig.model_validate(data)
    config_path = _write_config(
        args.config or default_config_path(args.unit), data, force=args.force
    )
    print(f"Wrote {config_path}")

    if ServiceMode(args.service) is ServiceMode.NONE:
        print(f"Start it with: {sys.executable} -m band_agentd run --config {config_path}")
        return

    scope = default_scope()
    unit_file, warning = install_systemd_service(config_path, unit_name=args.unit, scope=scope)
    flag = " --user" if scope is ServiceScope.USER else ""
    print(f"Installed and started {unit_file}")
    print(f"Status: systemctl{flag} status {args.unit}")
    print(f"Logs:   journalctl{flag} -u {args.unit} -f")
    print(f"Remove: band-agentd remove {args.unit}")
    if warning:
        print(f"Warning: {warning}")


def _remove(unit: str) -> None:
    config_path = default_config_path(unit)
    unit_file = remove_systemd_service(unit, default_scope())
    config_existed = config_path.exists()
    if config_existed:
        config_path.unlink()

    if unit_file is None and not config_existed:
        installed = sorted(path.stem for path in config_path.parent.glob("*.yaml"))
        raise ValueError(
            f"No agent named {unit!r} on this machine. Installed: {', '.join(installed) or 'none'}"
        )

    if unit_file is not None:
        print(f"Stopped the service and removed {unit_file}")
    if config_existed:
        print(f"Removed {config_path}")
    print(
        "Work branches (band/<room-id>) and their worktrees under "
        "~/.local/share/band-agentd/worktrees are kept. The agent still exists on Band; "
        "delete it from its menu on app.band.ai if you no longer need it."
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "install":
            _install(args)
            return 0
        if args.command == "run":
            logging_config()
            asyncio.run(AgentDaemon.from_path(args.config).run())
            return 0
        if args.command == "models":
            check_runtime(args.adapter)
            models = asyncio.run(list_models(args.adapter))
            if args.json:
                print(json.dumps([option.to_json() for option in models], indent=2))
            else:
                print(format_models(args.adapter, models))
            return 0
        if args.command == "init":
            print(_write_config(args.config, _starter_config(args), force=args.force))
            return 0
        if args.command == "remove":
            _remove(args.unit)
            return 0
        if args.command == "systemd":
            print(render_systemd_unit(args.config, unit_name=args.unit, scope=default_scope()))
            return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"band-agentd: {exc}", file=sys.stderr)
        return 2
    return 2


def logging_config() -> None:
    import logging

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # One line per Band API request otherwise buries agent events and errors.
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
