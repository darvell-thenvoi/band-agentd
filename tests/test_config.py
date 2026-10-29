from pathlib import Path

import pytest

from band_agentd.config import load_config


def write_config(path: Path, *, cwd: str = ".") -> None:
    path.write_text(
        """
agent:
  id: agent-id
  api_key: agent-key
  name: Test coder
  description: A test coding agent for Band rooms.
runtime:
  adapter: codex
  cwd: %s
  instructions_file: instructions.md
"""
        % cwd,
        encoding="utf-8",
    )


def test_load_config_keeps_credentials_in_config_and_resolves_paths(tmp_path):
    (tmp_path / "instructions.md").write_text("Work in the repo.", encoding="utf-8")
    config_path = tmp_path / "agent.yaml"
    write_config(config_path)

    config = load_config(config_path)

    assert config.require_credentials() == ("agent-id", "agent-key")
    assert config.runtime.cwd == tmp_path.resolve()
    assert config.resolved_instructions(config_path) == "Work in the repo."


def test_load_config_rejects_short_description(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        "agent:\n  description: short\nruntime:\n  cwd: .\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="at least 10"):
        load_config(config_path)
