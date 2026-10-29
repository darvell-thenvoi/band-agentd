from __future__ import annotations

import asyncio
import logging
import math
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import DaemonConfig, load_config
from .workspaces import room_workspace_resolver

logger = logging.getLogger(__name__)


def _emit_values(config: DaemonConfig) -> set[Any]:
    from band.core.types import Emit

    emit: set[Emit] = set()
    runtime = config.runtime
    if runtime.emit_tool_calls:
        emit.add(Emit.TOOL_CALLS)
    if runtime.emit_thoughts:
        emit.add(Emit.THOUGHTS)
    if runtime.emit_tasks:
        emit.add(Emit.TASK_EVENTS)
    if runtime.emit_usage:
        emit.add(Emit.USAGE)
    return emit


def build_adapter(config: DaemonConfig) -> Any:
    runtime = config.runtime
    workspace_for_room = room_workspace_resolver(runtime.cwd)
    instructions = config.resolved_instructions(Path.cwd())
    approval_mode = "auto_accept" if runtime.yolo else runtime.approval_mode

    if runtime.adapter == "codex":
        from band.adapters.codex import CodexAdapter, CodexAdapterConfig

        # "never" stops Codex from asking at all, so room approvals only work
        # when Codex is allowed to request escalation ("on-request").
        return CodexAdapter(
            config=CodexAdapterConfig(
                workspace_for_room=workspace_for_room,
                model=runtime.model,
                reasoning_effort=runtime.reasoning_effort,
                custom_section=instructions or "",
                approval_mode=approval_mode,
                approval_policy="never" if runtime.yolo else "on-request",
                sandbox=runtime.sandbox
                or ("danger-full-access" if runtime.yolo else "workspace-write"),
                # Codex's adapter requires a numeric value; infinity keeps the
                # SDK's wait bounded by process shutdown rather than a turn timer.
                turn_timeout_s=math.inf,
            ),
            emit=_emit_values(config),
        )

    from band.adapters.claude_sdk import (
        ClaudeApprovalOptions,
        ClaudePermissionMode,
        ClaudeSDKAdapter,
        ClaudeSDKAdapterConfig,
    )

    permission_mode = (
        ClaudePermissionMode.BYPASS_PERMISSIONS
        if runtime.yolo
        else ClaudePermissionMode(runtime.permission_mode)
    )
    # Room approvals route every native tool call, reads included, through
    # the room. Plan mode is already read-only, so it needs none.
    approvals = None
    if not runtime.yolo and permission_mode is not ClaudePermissionMode.PLAN:
        approvals = ClaudeApprovalOptions(mode=approval_mode)

    from band.core.types import Emit

    emit = _emit_values(config)
    emit.discard(Emit.TASK_EVENTS)
    return ClaudeSDKAdapter(
        config=ClaudeSDKAdapterConfig(
            model=runtime.model,
            effort=runtime.reasoning_effort,
            custom_section=instructions,
            permission_mode=permission_mode,
            max_thinking_tokens=runtime.max_thinking_tokens,
            turn_timeout_s=None,
            approvals=approvals,
        ),
        workspace_for_room=workspace_for_room,
        emit=emit,
    )


def build_agent(config: DaemonConfig, adapter: Any) -> Any:
    from band import Agent

    agent_id, api_key = config.require_credentials()
    return Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
    )


class AgentDaemon:
    """Keep a Band adapter process connected until the service is stopped."""

    def __init__(
        self,
        config: DaemonConfig,
        *,
        config_path: Path | None = None,
        adapter_factory: Callable[[DaemonConfig], Any] = build_adapter,
        agent_factory: Callable[[DaemonConfig, Any], Any] = build_agent,
    ) -> None:
        self.config = config
        self.config_path = config_path or Path.cwd() / "band-agentd.yaml"
        self.adapter_factory = adapter_factory
        self.agent_factory = agent_factory
        self._stopping = asyncio.Event()
        self._reload_requested = False

    @classmethod
    def from_path(cls, path: str | Path) -> AgentDaemon:
        config_path = Path(path).expanduser().resolve()
        return cls(load_config(config_path), config_path=config_path)

    def request_stop(self, _signum: int | None = None) -> None:
        self._stopping.set()

    async def run(self) -> None:
        self._install_host_signals()
        delay = self.config.restart.initial_delay_s

        while not self._stopping.is_set():
            if self._reload_requested:
                await self._reload_config()
                if self._reload_requested:
                    continue

            try:
                await self._run_agent_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._stopping.is_set():
                    break
                logger.exception("Agent stopped unexpectedly")
            else:
                if self._stopping.is_set():
                    break
                if self._reload_requested:
                    continue
                logger.warning("Agent connection ended")

            if self._reload_requested:
                continue
            if not self.config.restart.enabled:
                break
            logger.info("Restarting agent in %.1f seconds", delay)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except TimeoutError:
                delay = min(
                    max(delay * 2, self.config.restart.initial_delay_s),
                    self.config.restart.max_delay_s,
                )
            else:
                break

    async def _run_agent_once(self) -> None:
        from band.runtime.shutdown import GracefulShutdown

        adapter = self.adapter_factory(self.config)
        agent = self.agent_factory(self.config, adapter)
        shutdown = GracefulShutdown(
            agent,
            timeout=self.config.shutdown_timeout_s,
            on_signal=self.request_stop,
        )

        logger.info(
            "Starting %s agent '%s' in %s",
            self.config.runtime.adapter,
            self.config.agent.name,
            self.config.runtime.cwd,
        )
        async with shutdown, agent:
            run_task = asyncio.create_task(
                agent.run_forever(install_signal_handlers=False)
            )
            watch_task = asyncio.create_task(self._watch_files())
            try:
                done, _ = await asyncio.wait(
                    (run_task, watch_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if watch_task in done and not self._stopping.is_set():
                    self._reload_requested = True
                    logger.info("Config or instructions changed; reloading agent")
                    await agent.stop(timeout=self.config.shutdown_timeout_s)
                await run_task
            finally:
                if not watch_task.done():
                    watch_task.cancel()
                await asyncio.gather(watch_task, return_exceptions=True)

    async def _watch_files(self) -> None:
        watched = self._watched_files()
        previous = self._file_snapshot(watched)
        while True:
            await asyncio.sleep(self.config.reload_interval_s)
            current = self._file_snapshot(watched)
            if current != previous:
                return

    def _watched_files(self) -> tuple[Path, ...]:
        paths = [self.config_path]
        instructions_file = self.config.runtime.instructions_file
        if instructions_file is not None:
            paths.append(instructions_file)
        return tuple(paths)

    @staticmethod
    def _file_snapshot(paths: tuple[Path, ...]) -> tuple[tuple[str, int, int], ...]:
        snapshot: list[tuple[str, int, int]] = []
        for path in paths:
            try:
                info = path.stat()
            except FileNotFoundError:
                snapshot.append((str(path), 0, 0))
            else:
                snapshot.append((str(path), info.st_mtime_ns, info.st_size))
        return tuple(snapshot)

    async def _reload_config(self) -> None:
        try:
            self.config = load_config(self.config_path)
        except (OSError, ValueError) as exc:
            logger.error("Config reload failed: %s", exc)
            await asyncio.sleep(self.config.reload_interval_s)
            return
        self._reload_requested = False
        logger.info("Reloaded config from %s", self.config_path)

    def _install_host_signals(self) -> None:
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, self.request_stop, signum)
            except (NotImplementedError, RuntimeError):
                logger.debug("Could not install signal handler for %s", signum)
