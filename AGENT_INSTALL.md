# Installing band-agentd (instructions for coding agents)

Follow this runbook when an operator asks you to set up Band agents on this machine. Each Band agent ends up running as its own systemd service, backed by Codex or Claude, with its credentials in an owner-only config file. One machine can run any number of agents.

## Rules

- Each shell command may run in a fresh shell with no terminal attached. Start every command with `export PATH="$HOME/.local/bin:$PATH";` and never run anything that waits for keyboard input.
- Follow the steps in order. In each message to the operator, ask only what the current step needs. Never ask for an agent ID or API key before step 6, where the operator first gets the name and description to create the agent with.
- Do the installation yourself. Never hand the operator these commands to run in another terminal. The only commands the operator runs are sign-ins (step 4) and, when step 7 says so, `sudo loginctl enable-linger`.
- Never print, echo, log, or commit an agent API key after the operator gives it to you. Pass it to the installer only through stdin, as shown in step 7.
- Do not ask for a human or user API key. Agent API keys come from the Band website.
- Configuration fields are documented in `config.example.yaml` in this repository. Read it before answering configuration questions.

## 0. Get write access outside this folder

The install writes to `~/.local`, `~/.cache`, `~/.config`, and systemd, and it downloads packages. Confirm that you can:

```bash
export PATH="$HOME/.local/bin:$PATH"; mkdir -p "$HOME/.local/share" "$HOME/.cache" "$HOME/.config" && touch "$HOME/.local/share/.band-agentd-probe" "$HOME/.cache/.band-agentd-probe" && rm "$HOME/.local/share/.band-agentd-probe" "$HOME/.cache/.band-agentd-probe" && curl -fsS -o /dev/null https://github.com && echo access-ok
```

If `access-ok` does not print, rerun the same command with escalated permissions; in Codex, that sends the operator an approval request. If escalation is unavailable or refused, stop and send the operator exactly this:

> The install needs to write outside this folder and use the network. In Codex, type `/permissions`, choose **Full Access**, and tell me to continue. In Claude Code, approve the commands when asked.

Do not continue to step 1 until `access-ok` prints.

## 1. Check the machine

```bash
export PATH="$HOME/.local/bin:$PATH"; uname -s; id -un; id -u; command -v git curl systemctl; command -v codex claude; [ "$(id -u)" = 0 ] || (systemctl --user show-environment >/dev/null 2>&1 && echo user-systemd-ok)
```

Continue only on Linux with `git`, `curl`, and `systemctl`. When `id -u` is not `0`, `user-systemd-ok` must also appear. If systemd is missing, install with `--service none` and tell the operator that each agent must then be started with `band-agentd run`.

## 2. Install uv and band-agentd

```bash
export PATH="$HOME/.local/bin:$PATH"; command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
export PATH="$HOME/.local/bin:$PATH"; SRC="$HOME/.local/share/band-agentd/src"; if [ -d "$SRC/.git" ]; then git -C "$SRC" pull --ff-only; else git clone https://github.com/darvell-thenvoi/band-agentd "$SRC"; fi; uv tool install --force "${SRC}[codex,claude]" && band-agentd --help >/dev/null && echo band-agentd-ok
```

Keep the braces in `"${SRC}[codex,claude]"`. Without them, zsh reads `[codex,claude]` as an array subscript. A copy you cloned elsewhere to read this file can stay where it is; band-agentd installs from this one.

## 3. Ask which agents to create

Ask the operator in one message. Do not ask for an ID or API key yet. Offer an example, such as "one Codex agent working on `~/src/api`":

1. **How many agents**, and for each one:
   - **Runtime:** `codex` or `claude`. Recommend the runtime the operator is using with you right now, because it is already installed and signed in on this machine.
   - **Working directory:** the repository or directory it works in.
   - **Role** (optional): one or two sentences about what it is responsible for. This becomes the agent's instructions.
2. **YOLO mode:** yes or no, for all agents or per agent. Default to no. YOLO removes every approval prompt and lets the agent run any command as this user.

Check that every working directory exists.

## 4. Make sure each runtime in use is signed in

Codex:

```bash
export PATH="$HOME/.local/bin:$PATH"; command -v codex && codex login status
```

If `codex` is missing, install it with `npm install -g @openai/codex`. If `codex login status` fails, ask the operator to run `codex login --device-auth` in their own terminal on this machine, then wait for them to confirm.

Claude: the Claude Code CLI ships inside band-agentd, so nothing needs installing. Step 5 reports whether it is signed in. If it is not, give the operator the sign-in command from the error message.

## 5. Choose a model and reasoning level for each agent

List what this machine's login offers, once for each runtime in use:

```bash
export PATH="$HOME/.local/bin:$PATH"; band-agentd models --adapter codex
```

```bash
export PATH="$HOME/.local/bin:$PATH"; band-agentd models --adapter claude
```

Show the operator the list as printed: each model id, its description, and its reasoning levels, with `*` marking the default. Ask for each agent's model and reasoning level, and offer the default model at its default level as the choice when they have no preference. Use only ids and levels from the list. Add `--json` for machine-readable output.

Then propose a name and description for each agent:

- **Name:** 3 to 24 characters, using only letters, numbers, and spaces, and unique on this machine, for example `Api Coder`.
- **Description:** at least 10 characters about what the agent does, for example `Coding agent for the api repository on build-box`.
- **Unit:** the name in lowercase, with hyphens, for example `api-coder`. It names the service and the config file.

## 6. Have the operator create each Band agent

For each agent, send these steps, filled in with the name and description you proposed:

1. Open https://app.band.ai/agents/create
2. **Agent name:** `<name>`
3. **Description:** `<description>`
4. Leave **Handle** as generated. **Tag your agent** is optional.
5. Select **Connect Agent**.
6. Copy the **ID** and **API Key** from the result and paste both here. The key is shown only once. If it is lost, generate a new one from the agent's menu on the website.

The ID is a UUID. If the operator pastes a handle such as `@name/agent`, ask for the ID instead. You may collect all agents' credentials before installing, or install each agent as its credentials arrive.

## 7. Install each agent

Run this once per agent, filling in its values. Leave out `--instructions` when no role was given, leave out `--model` and `--reasoning-effort` when the operator chose the defaults, and add `--yolo` only when the operator chose it.

```bash
export PATH="$HOME/.local/bin:$PATH"; printf '%s\n' '<API key>' | band-agentd install \
  --adapter <codex|claude> \
  --cwd <working directory> \
  --agent-id <ID> \
  --api-key-stdin \
  --name '<name>' \
  --description '<description>' \
  --instructions '<role>' \
  --model <model id> \
  --reasoning-effort <level> \
  --unit <unit>
```

The installer:

- checks that the runtime is installed and signed in, and that the model and reasoning level are offered
- verifies the ID and key with Band and prints the agent name Band reports
- writes `~/.config/band-agentd/<unit>.yaml` with mode `0600`
- installs and starts a systemd service: a user service when not root, a system service when root
- records the current `PATH` and `HOME` in the unit, so the service finds the same `codex` binary and logins

If it exits with an error, the message names the fix. Correct the cause and rerun the same command, adding `--force` once a config file exists. If it prints a lingering warning, give the operator the `sudo loginctl enable-linger ...` command it shows. Without lingering, a user service stops when the operator logs out.

## 8. Confirm each agent is connected

```bash
export PATH="$HOME/.local/bin:$PATH"; systemctl --user status <unit> --no-pager; journalctl --user -u <unit> -n 40 --no-pager | grep -E 'Agent started|ERROR|Error'
```

Drop `--user` from both commands when installed as root. `Agent started` means the agent is online.

## 9. Tell the operator how to use the agents

Send a short summary covering these points:

- **Start work:** add the agent to a room on app.band.ai and @mention it. An agent wakes only when mentioned. One agent can work in many rooms at once.
- **Where it works:** in a git repository, each room gets its own worktree on a branch named `band/<room-id>`, so the work shows up as branches in the original repository. Outside git, each room gets its own folder under the working directory.
- **Approvals** (without YOLO): the agent posts requests in the room. Reply `/approve <id>` or `/decline <id>`. Codex also accepts `/approve-session <id>`.
- **Changing settings:** edit `~/.config/band-agentd/<unit>.yaml`. Saving restarts that agent automatically. Every field is explained in `~/.local/share/band-agentd/src/config.example.yaml`. Common changes are `runtime.instructions` for the role, `runtime.model` and `runtime.reasoning_effort` (choices from `band-agentd models --adapter <runtime>`), `runtime.yolo`, and `runtime.approval_mode`.
- **Status and logs:** `systemctl --user status <unit>` and `journalctl --user -u <unit> -f`, without `--user` for a root install.
- **Adding another agent later:** ask a coding agent on this machine to run this runbook again.
- **Removing an agent:** `systemctl --user disable --now <unit>`, then delete its config file and unit file.
