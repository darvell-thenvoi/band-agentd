from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CODEX_PAGE_LIMIT = 100
CLAUDE_DEFAULT_ENTRY = "default"


@dataclass(frozen=True)
class ModelOption:
    id: str
    name: str
    description: str
    is_default: bool
    efforts: tuple[str, ...]
    default_effort: str | None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["efforts"] = list(self.efforts)
        return data


def codex_ready() -> None:
    if shutil.which("codex") is None:
        raise RuntimeError(
            "Codex CLI is not on PATH. Install it with `npm install -g @openai/codex`."
        )
    status = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
    if status.returncode != 0:
        raise RuntimeError(
            "Codex is not signed in. Sign in on this machine with "
            "`codex login --device-auth`, then rerun install."
        )


def claude_cli() -> str:
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise RuntimeError(
            "The Claude runtime is not installed. Reinstall band-agentd with the claude extra."
        ) from exc

    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if bundled.is_file():
        return str(bundled)
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    raise RuntimeError("No Claude Code CLI found in claude-agent-sdk or on PATH.")


def claude_ready() -> None:
    cli = claude_cli()
    status = subprocess.run([cli, "auth", "status", "--json"], capture_output=True, text=True)
    try:
        logged_in = bool(json.loads(status.stdout).get("loggedIn"))
    except json.JSONDecodeError:
        logged_in = False
    if logged_in:
        return
    login = "claude auth login" if shutil.which("claude") else f"{cli} auth login"
    raise RuntimeError(
        f"Claude is not signed in. Sign in on this machine with `{login}`, then rerun install."
    )


def check_runtime(adapter: str) -> None:
    if adapter == "codex":
        codex_ready()
        return
    claude_ready()


async def _codex_models() -> list[ModelOption]:
    from band.integrations.codex import CodexStdioClient

    client = CodexStdioClient()
    await client.connect()
    try:
        await client.initialize(
            client_name="band_agentd", client_title="band-agentd", client_version="0"
        )
        entries: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": CODEX_PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            page = await client.request("model/list", params)
            entries += [entry for entry in page.get("data", []) if isinstance(entry, dict)]
            cursor = page.get("nextCursor")
            if not cursor:
                break
    finally:
        await client.close()

    return [
        ModelOption(
            id=entry["id"],
            name=entry.get("displayName") or entry["id"],
            description=entry.get("description") or "",
            is_default=bool(entry.get("isDefault")),
            efforts=tuple(
                effort["reasoningEffort"]
                for effort in entry.get("supportedReasoningEfforts") or []
                if isinstance(effort, dict) and effort.get("reasoningEffort")
            ),
            default_effort=entry.get("defaultReasoningEffort"),
        )
        for entry in entries
        if entry.get("id") and not entry.get("hidden")
    ]


async def _claude_models() -> list[ModelOption]:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    options = ClaudeAgentOptions(cli_path=claude_cli(), setting_sources=[])
    async with ClaudeSDKClient(options) as client:
        info = await client.get_server_info() or {}

    entries = [entry for entry in info.get("models", []) if isinstance(entry, dict)]
    default_model = next(
        (
            entry.get("resolvedModel")
            for entry in entries
            if entry.get("value") == CLAUDE_DEFAULT_ENTRY
        ),
        None,
    )
    return [
        ModelOption(
            id=entry["value"],
            name=entry.get("displayName") or entry["value"],
            description=entry.get("description") or "",
            is_default=default_model is not None
            and entry.get("resolvedModel") == default_model,
            efforts=tuple(entry.get("supportedEffortLevels") or ())
            if entry.get("supportsEffort")
            else (),
            default_effort=None,
        )
        for entry in entries
        if entry.get("value") and entry.get("value") != CLAUDE_DEFAULT_ENTRY
    ]


async def list_models(adapter: str) -> list[ModelOption]:
    if adapter == "codex":
        return await _codex_models()
    return await _claude_models()


def validate_choice(
    models: list[ModelOption], model: str | None, effort: str | None
) -> None:
    """Reject a model or reasoning effort the signed-in account does not offer."""
    if model is None and effort is None:
        return

    by_id = {option.id: option for option in models}
    if model is not None and model not in by_id:
        raise ValueError(
            f"Model {model!r} is not available. Choose one of: {', '.join(by_id)}"
        )

    if effort is None:
        return
    chosen = by_id.get(model) if model else next((m for m in models if m.is_default), None)
    if chosen is None or not chosen.efforts:
        return
    if effort not in chosen.efforts:
        raise ValueError(
            f"Reasoning effort {effort!r} is not supported by {chosen.id}. "
            f"Choose one of: {', '.join(chosen.efforts)}"
        )


def format_models(adapter: str, models: list[ModelOption]) -> str:
    lines = [f"{adapter} models available to this machine's login (* = default):"]
    width = max((len(option.id) for option in models), default=0)
    for option in models:
        marker = "*" if option.is_default else " "
        efforts = " ".join(option.efforts) or "n/a"
        default_effort = f" (default {option.default_effort})" if option.default_effort else ""
        lines.append(f"{marker} {option.id.ljust(width)}  reasoning: {efforts}{default_effort}")
        if option.description:
            lines.append(f"  {' ' * width}  {option.description}")
    return "\n".join(lines)
