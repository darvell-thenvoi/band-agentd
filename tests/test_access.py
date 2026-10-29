import io

import pytest

from band_agentd.cli import main
from band_agentd.config import load_config
from band_agentd.daemon import build_adapter

AGENT_ID = "6f1c2c1e-6a3b-4c38-9d47-0b3d2f8a91aa"


def install(tmp_path, monkeypatch, adapter: str, access: str):
    monkeypatch.setattr("sys.stdin", io.StringIO("agent-secret-key\n"))
    config_path = tmp_path / f"{adapter}-{access}.yaml"
    assert (
        main(
            [
                "install",
                "--adapter",
                adapter,
                "--cwd",
                str(tmp_path),
                "--agent-id",
                AGENT_ID,
                "--api-key-stdin",
                "--access",
                access,
                "--service",
                "none",
                "--skip-checks",
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    return build_adapter(load_config(config_path)).config


@pytest.mark.parametrize(
    ("access", "sandbox", "approval_policy", "approval_mode"),
    [
        ("full", "danger-full-access", "never", "auto_accept"),
        ("ask", "workspace-write", "on-request", "manual"),
        ("read-only", "read-only", "on-request", "auto_decline"),
    ],
)
def test_codex_access_levels(tmp_path, monkeypatch, access, sandbox, approval_policy, approval_mode):
    config = install(tmp_path, monkeypatch, "codex", access)

    assert config.sandbox == sandbox
    assert config.approval_policy == approval_policy
    assert config.approval_mode == approval_mode


@pytest.mark.parametrize(
    ("access", "permission_mode", "approvals"),
    [
        ("full", "bypassPermissions", None),
        ("ask", "acceptEdits", "manual"),
        ("read-only", "plan", None),
    ],
)
def test_claude_access_levels(tmp_path, monkeypatch, access, permission_mode, approvals):
    config = install(tmp_path, monkeypatch, "claude", access)

    assert config.permission_mode == permission_mode
    assert (config.approvals.mode if config.approvals else None) == approvals
