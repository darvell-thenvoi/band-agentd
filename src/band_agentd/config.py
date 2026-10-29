from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

AdapterName = Literal["codex", "claude"]
ApprovalMode = Literal["manual", "auto_accept", "auto_decline"]


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    api_key: str | None = None
    name: str = "Band coding agent"
    description: str = "A coding agent that works in Band rooms."

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("agent.name must not be empty")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("agent.description must contain at least 10 characters")
        if len(value) > 500:
            raise ValueError("agent.description must contain at most 500 characters")
        return value


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: AdapterName = "codex"
    cwd: Path = Path(".")
    yolo: bool = False
    instructions: str | None = None
    instructions_file: Path | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    approval_mode: ApprovalMode = "manual"
    sandbox: str | None = None
    permission_mode: str = "acceptEdits"
    max_thinking_tokens: int | None = Field(default=None, gt=0)
    emit_tool_calls: bool = True
    emit_thoughts: bool = True
    emit_tasks: bool = True
    emit_usage: bool = True

    @field_validator("cwd", "instructions_file", mode="before")
    @classmethod
    def expand_path(cls, value: object) -> object:
        if value is None:
            return value
        return Path(os.path.expanduser(os.path.expandvars(str(value))))


class RestartConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    initial_delay_s: float = Field(default=2.0, ge=0)
    max_delay_s: float = Field(default=60.0, ge=0)

    @field_validator("max_delay_s")
    @classmethod
    def max_delay_at_least_initial(cls, value: float, info: object) -> float:
        initial = getattr(info, "data", {}).get("initial_delay_s", 0)
        if value < initial:
            raise ValueError("restart.max_delay_s must be at least initial_delay_s")
        return value


class DaemonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentConfig = Field(default_factory=AgentConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    restart: RestartConfig = Field(default_factory=RestartConfig)
    shutdown_timeout_s: float = Field(default=30.0, gt=0)
    reload_interval_s: float = Field(default=1.0, gt=0)

    def resolved_instructions(self, config_path: Path) -> str | None:
        if self.runtime.instructions_file is not None:
            path = self.runtime.instructions_file
            if not path.is_absolute():
                path = config_path.parent / path
            return path.read_text(encoding="utf-8").strip()
        return self.runtime.instructions.strip() if self.runtime.instructions else None

    def require_credentials(self) -> tuple[str, str]:
        agent_id = self.agent.id
        api_key = self.agent.api_key
        if not agent_id:
            raise ValueError("Missing agent.id in the config")
        if not api_key:
            raise ValueError("Missing agent.api_key in the config")
        return agent_id, api_key


def load_config(path: str | Path) -> DaemonConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file does not exist: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a YAML mapping")

    config = DaemonConfig.model_validate(raw)
    cwd = config.runtime.cwd
    if not cwd.is_absolute():
        cwd = (config_path.parent / cwd).resolve()
    config.runtime.cwd = cwd

    instructions_file = config.runtime.instructions_file
    if instructions_file is not None and not instructions_file.is_absolute():
        config.runtime.instructions_file = (config_path.parent / instructions_file).resolve()

    if not cwd.is_dir():
        raise ValueError(f"runtime.cwd is not a directory: {cwd}")
    return config
