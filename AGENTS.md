# band-agentd

This folder is band-agentd, which runs Band agents on this machine. A user who opens a coding agent here usually wants to add, change, or remove one of those agents.

- **Add, change, or remove an agent:** follow [AGENT_INSTALL.md](AGENT_INSTALL.md). It covers the setup conversation and, under "Later requests", how to find, change, and remove existing agents.
- **Agent settings:** `~/.config/band-agentd/<name>.yaml`, one file per agent. [config.example.yaml](config.example.yaml) explains every field. Saving a settings file restarts that agent automatically.
- **Working on band-agentd itself:** the code is in `src/band_agentd/`, and the tests run with `uv run pytest`. See the Development section of [README.md](README.md).
