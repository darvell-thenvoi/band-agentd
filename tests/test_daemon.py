import asyncio

import pytest
from gitrepo import make_repo

from band_agentd.config import DaemonConfig
from band_agentd.daemon import AgentDaemon, build_adapter


def test_codex_yolo_maps_to_unrestricted_native_settings(tmp_path):
    config = DaemonConfig.model_validate(
        {
            "agent": {
                "id": "agent-id",
                "api_key": "agent-key",
                "description": "A coding agent for test rooms.",
            },
            "runtime": {"adapter": "codex", "cwd": str(tmp_path), "yolo": True},
        }
    )

    adapter = build_adapter(config)

    assert adapter.config.approval_mode == "auto_accept"
    assert adapter.config.approval_policy == "never"
    assert adapter.config.sandbox == "danger-full-access"
    assert adapter.config.turn_timeout_s == float("inf")


def test_codex_rooms_share_the_working_directory_by_default(tmp_path):
    config = DaemonConfig.model_validate({"runtime": {"adapter": "codex", "cwd": str(tmp_path)}})

    adapter = build_adapter(config)

    with adapter._workspaces.claiming("room-1") as first:
        with adapter._workspaces.claiming("room-2") as second:
            assert first == second == str(tmp_path.resolve())


def test_claude_works_in_the_working_directory_by_default(tmp_path):
    config = DaemonConfig.model_validate({"runtime": {"adapter": "claude", "cwd": str(tmp_path)}})

    assert build_adapter(config).config.cwd == tmp_path


@pytest.mark.parametrize("adapter_name", ["codex", "claude"])
def test_worktree_mode_gives_rooms_their_own_checkout(tmp_path, monkeypatch, adapter_name):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = make_repo(tmp_path / "repo")
    config = DaemonConfig.model_validate(
        {"runtime": {"adapter": adapter_name, "cwd": str(repo), "workspace": "worktree"}}
    )

    adapter = build_adapter(config)

    assert adapter._workspaces.claim("room-1") != adapter._workspaces.claim("room-2")
    assert "worktrees" in adapter._workspaces.claim("room-1")


def test_codex_default_routes_escalations_to_room_approvals(tmp_path):
    config = DaemonConfig.model_validate(
        {"runtime": {"adapter": "codex", "cwd": str(tmp_path)}}
    )

    adapter = build_adapter(config)

    assert adapter.config.approval_mode == "manual"
    assert adapter.config.approval_policy == "on-request"
    assert adapter.config.sandbox == "workspace-write"


def test_file_watcher_notices_instruction_changes(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text("agent: {}\n", encoding="utf-8")
    instructions = tmp_path / "instructions.md"
    instructions.write_text("First version", encoding="utf-8")
    config = DaemonConfig.model_validate(
        {
            "runtime": {
                "cwd": str(tmp_path),
                "instructions_file": str(instructions),
            },
            "reload_interval_s": 0.01,
        }
    )
    daemon = AgentDaemon(config, config_path=config_path)

    async def exercise() -> None:
        watcher = asyncio.create_task(daemon._watch_files())
        await asyncio.sleep(0.02)
        instructions.write_text("Second version", encoding="utf-8")
        await asyncio.wait_for(watcher, timeout=0.5)

    asyncio.run(exercise())


def test_agent_restarts_when_watched_file_changes(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text("agent: {}\n", encoding="utf-8")
    instructions = tmp_path / "instructions.md"
    instructions.write_text("First version", encoding="utf-8")
    config = DaemonConfig.model_validate(
        {
            "runtime": {
                "cwd": str(tmp_path),
                "instructions_file": str(instructions),
            },
            "reload_interval_s": 0.01,
        }
    )

    class FakeAgent:
        def __init__(self) -> None:
            self.done = asyncio.Event()
            self.stopped = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def run_forever(self, *, install_signal_handlers: bool):
            await self.done.wait()

        async def stop(self, *, timeout: float):
            self.stopped = True
            self.done.set()

    fake = FakeAgent()
    daemon = AgentDaemon(
        config,
        config_path=config_path,
        adapter_factory=lambda _config: object(),
        agent_factory=lambda _config, _adapter: fake,
    )

    async def exercise() -> None:
        run = asyncio.create_task(daemon._run_agent_once())
        await asyncio.sleep(0.02)
        instructions.write_text("Second version", encoding="utf-8")
        await asyncio.wait_for(run, timeout=0.5)

    asyncio.run(exercise())
    assert fake.stopped
    assert daemon._reloading


def test_invalid_settings_change_keeps_the_agent_running(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text("agent: {}\n", encoding="utf-8")
    config = DaemonConfig.model_validate(
        {"runtime": {"cwd": str(tmp_path)}, "reload_interval_s": 0.01}
    )
    daemon = AgentDaemon(config, config_path=config_path)

    async def exercise() -> None:
        watcher = asyncio.create_task(daemon._watch_files())
        await asyncio.sleep(0.02)
        config_path.write_text("runtime:\n  adapter: nonsense\n", encoding="utf-8")
        await asyncio.sleep(0.1)
        assert not watcher.done()
        config_path.write_text("runtime:\n  adapter: claude\n", encoding="utf-8")
        await asyncio.wait_for(watcher, timeout=0.5)

    asyncio.run(exercise())
