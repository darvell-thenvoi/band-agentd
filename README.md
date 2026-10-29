# band-agentd

band-agentd runs Band agents backed by Codex or Claude on a Linux machine, one systemd service per agent. Each Band room gets its own native session and its own git worktree of the working directory. Each agent's settings live in one YAML file, and saving it restarts that agent automatically.

## Set up agents with a coding agent

SSH into the machine and start `codex` or `claude`. In Codex, first type `/permissions` and choose **Ask for approval**. Codex's default mode silently refuses the setup's requests to install packages and write outside the current folder, while this mode asks you before each one. In Claude Code, approve commands as they come up. Then paste:

```text
Set up Band agents on this machine. Clone https://github.com/darvell-thenvoi/band-agentd
and follow AGENT_INSTALL.md in it exactly.
```

The agent installs band-agentd, then walks you through a short conversation:

1. Do you want an agent now, and should it run on Codex or Claude?
2. What should it be called, and what will it do?
3. Which model and reasoning level? It lists what your login offers and suggests one.
4. Create the agent on https://app.band.ai/agents/create with the name and description it gives you, then paste back the ID and API key.

It then installs the agent as a service, checks that it is online, fixes anything that goes wrong, and tells you how to start using it in Band.

**For coding agents:** read [AGENT_INSTALL.md](AGENT_INSTALL.md) and follow it step by step. It is written for a shell with no terminal attached.

## Install by hand

Requirements: Linux with systemd and git, plus a signed-in runtime. For Codex, `codex login status` must succeed. For Claude, the Claude Code CLI ships with the package, so you only need to be signed in.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
git clone https://github.com/darvell-thenvoi/band-agentd ~/.local/share/band-agentd/src
uv tool install --force "${HOME}/.local/share/band-agentd/src[codex,claude]"
```

Create the agent on the Band website:

1. Open https://app.band.ai/agents/create
2. Enter an **Agent name** (3 to 24 letters, numbers, or spaces) and a **Description** (at least 10 characters).
3. Select **Connect Agent**.
4. Copy the **ID** and **API Key**. The key is shown only once. A lost key can be replaced from the agent's menu, and the old key stops working.

![Band web Connect Remote Agent form, with the account handle redacted](docs/images/agent-connect-form.png)

Then install and start the service. Run this from a terminal, and the installer asks for anything you leave out. Repeat with a different `--unit` for each additional agent. `band-agentd models --adapter codex` lists the models and reasoning levels you can pass with `--model` and `--reasoning-effort`:

```bash
band-agentd install --adapter codex --cwd ~/src/my-repo --unit my-coder
```

From a script, pass every value as a flag and send the key on stdin:

```bash
printf '%s\n' "$KEY" | band-agentd install --adapter codex --cwd ~/src/my-repo \
  --agent-id <ID> --api-key-stdin --unit my-coder
```

`install` checks that the runtime is installed and signed in, and verifies the ID and key with Band. It then writes `~/.config/band-agentd/<unit>.yaml` with mode `0600`, installs a systemd unit, and starts it. Run as a regular user, it installs a user service in `~/.config/systemd/user`. Run as root, it installs a system service. The unit records the installing shell's `PATH` and `HOME`, so the service finds the same `codex` binary and logins.

A user service stops when you log out unless lingering is enabled. The installer enables it when it can. Otherwise it prints the one `sudo loginctl enable-linger <user>` command to run.

Check on it:

```bash
systemctl --user status my-coder
journalctl --user -u my-coder -f
```

Drop `--user` for a root install. Use `--service none` on machines without systemd, then run `band-agentd run --config ~/.config/band-agentd/my-coder.yaml` under your own supervisor.

## Using the agent

Add the agent to a room on app.band.ai and @mention it. A mention is the only thing that wakes it. One process serves any number of rooms at once.

**Workspaces.** If `runtime.cwd` is inside a git repository, each room gets a worktree of that repository under `~/.local/share/band-agentd/worktrees/` on a branch named `band/<room-id>`, at the same subdirectory as `cwd`. Rooms never share a checkout, and their work shows up in the original repository as branches. A worktree starts from the repository's committed `HEAD`, so uncommitted changes in your own checkout are not included. If `cwd` is not in a git repository, each room gets an empty directory `<cwd>/<room-id>`.

**Approvals.** Without YOLO mode, Codex works in its `workspace-write` sandbox: it reads, edits, and runs commands inside its worktree without asking, and asks before anything outside it, such as network access or writing to `.git`. Claude asks before every native tool call, including file reads, which is a lot of prompts; on a trusted machine set `approval_mode: auto_accept` for Claude. Each request appears in the room. Reply `/approve <id>` or `/decline <id>`. Codex also accepts `/approve-session <id>` to allow similar requests for the rest of the session. Unanswered requests are declined after 5 minutes.

**YOLO mode.** `yolo: true` runs Codex with `danger-full-access` and no approval prompts, and runs Claude with `bypassPermissions`. Use it only on a machine where the agent may run any command as the service user.

**Turns** have no time limit. Stopping the service lets the current turn finish for up to `shutdown_timeout_s` seconds.

## Configuration

Each agent has its own file, `~/.config/band-agentd/<unit>.yaml`, which `install` writes. [config.example.yaml](config.example.yaml) explains every field. Edit the file in place, and the daemon restarts that agent within `reload_interval_s` seconds of a save. If the file can't be parsed, the daemon logs the error and keeps retrying until it is valid.

Common changes:

| Field | Effect |
| --- | --- |
| `runtime.instructions` | The agent's role, added to its system prompt |
| `runtime.model` | Model id; `band-agentd models --adapter codex` (or `claude`) lists the ones this machine's login offers |
| `runtime.reasoning_effort` | Reasoning level for that model, from the same list |
| `runtime.yolo` | `true` removes all approval prompts |
| `runtime.approval_mode` | `manual`, `auto_accept`, or `auto_decline` for approval requests |
| `runtime.cwd` | Repository or directory the agent works in |
| `runtime.adapter` | `codex` or `claude` |

Do not put a user API key (`band_u_…` or `thnv_u_…`) in `agent.api_key`. It needs the key Band generated for this agent.

## Development

```bash
uv sync --extra codex --extra claude
uv run pytest
```
