import io
import stat
from types import SimpleNamespace

import pytest

from band_agentd import cli
from band_agentd.cli import main
from band_agentd.config import load_config
from band_agentd.runtimes import ModelOption

AGENT_ID = "6f1c2c1e-6a3b-4c38-9d47-0b3d2f8a91aa"


def install_args(tmp_path, *extra: str) -> list[str]:
    return [
        "install",
        "--adapter",
        "codex",
        "--cwd",
        str(tmp_path),
        "--agent-id",
        AGENT_ID,
        "--api-key-stdin",
        "--service",
        "none",
        "--config",
        str(tmp_path / "conf" / "agent.yaml"),
        *extra,
    ]


def test_install_runs_without_a_terminal_and_keeps_the_key_private(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("sys.stdin", io.StringIO("agent-secret-key\n"))

    result = main(install_args(tmp_path, "--skip-checks"))

    config_path = tmp_path / "conf" / "agent.yaml"
    assert result == 0
    assert load_config(config_path).require_credentials() == (AGENT_ID, "agent-secret-key")
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(config_path.parent.stat().st_mode) == 0o700
    output = capsys.readouterr()
    assert "agent-secret-key" not in output.out + output.err


def test_install_without_terminal_names_the_missing_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    result = main(["install", "--adapter", "codex", "--cwd", str(tmp_path), "--service", "none"])

    assert result == 2
    assert "--agent-id is required" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("band_u_abc", "user API key"),
        ("", "empty"),
    ],
)
def test_install_rejects_wrong_keys(tmp_path, monkeypatch, capsys, key, message):
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{key}\n"))

    result = main(install_args(tmp_path, "--skip-checks"))

    assert result == 2
    assert message in capsys.readouterr().err
    assert not (tmp_path / "conf" / "agent.yaml").exists()


def test_install_rejects_a_handle_instead_of_an_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("agent-secret-key\n"))
    args = install_args(tmp_path, "--skip-checks")
    args[args.index(AGENT_ID)] = "@darv/coder"

    assert main(args) == 2
    assert "UUID" in capsys.readouterr().err


def test_install_rejects_a_service_name_systemd_cannot_use(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("agent-secret-key\n"))

    assert main(install_args(tmp_path, "--skip-checks", "--unit", "my agent")) == 2
    assert "Service name" in capsys.readouterr().err


def test_install_checks_worktree_mode_before_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("agent-secret-key\n"))

    assert main(install_args(tmp_path, "--skip-checks", "--workspace", "worktree")) == 2
    assert "needs a git repository" in capsys.readouterr().err
    assert not (tmp_path / "conf" / "agent.yaml").exists()


def test_install_without_systemd_fails_before_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("agent-secret-key\n"))
    monkeypatch.setattr("band_agentd.service.shutil.which", lambda _name: None)
    args = install_args(tmp_path, "--skip-checks")
    args[args.index("none")] = "systemd"

    assert main(args) == 2
    assert "--service none" in capsys.readouterr().err
    assert not (tmp_path / "conf" / "agent.yaml").exists()


def test_install_rejects_a_model_the_login_does_not_offer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("agent-secret-key\n"))
    monkeypatch.setattr(cli, "check_runtime", lambda _adapter: None)

    async def models(_adapter):
        return [ModelOption("gpt-x", "X", "", True, ("low",), "low")]

    monkeypatch.setattr(cli, "list_models", models)

    result = main(install_args(tmp_path, "--model", "gpt-y"))

    assert result == 2
    assert "gpt-x" in capsys.readouterr().err
    assert not (tmp_path / "conf" / "agent.yaml").exists()


def test_install_refuses_credentials_for_a_different_agent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("agent-secret-key\n"))
    monkeypatch.setattr(cli, "check_runtime", lambda _adapter: None)

    class FakeIdentity:
        async def get_agent_me(self, **_kwargs):
            return SimpleNamespace(
                data=SimpleNamespace(id="00000000-0000-0000-0000-000000000000", name="x", handle="")
            )

    class FakeClient:
        def __init__(self, **_kwargs):
            self.agent_api_identity = FakeIdentity()

    async def no_close(_client):
        return None

    monkeypatch.setattr("band.client.rest.AsyncRestClient", FakeClient)
    monkeypatch.setattr("band.client.rest.aclose_rest_client", no_close)

    result = main(install_args(tmp_path))

    assert result == 2
    assert "belongs to agent" in capsys.readouterr().err
    assert not (tmp_path / "conf" / "agent.yaml").exists()
