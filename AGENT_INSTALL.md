# Setting up Band agents (instructions for coding agents)

Use this when the user asks you to set up, change, or remove Band agents on this machine. To set one up, you install band-agentd through a short conversation and connect a Band agent that runs on Codex or Claude, then leave it running as a service. You do all the technical work. The user answers a few plain questions and creates the agent on the Band website. For changes or removal of existing agents, go to "Later requests" at the end.

## How to talk to the user

- Ask one question per message, in plain words. Say "agent", "Codex", "Claude", and "model". Never say "unit", "adapter", "runtime", "systemd", or "config" unless the user asks how something works.
- Put a suggested answer in every question, so the user can reply "yes" or "sounds good".
- Work silently between questions. Mention a problem only when you need the user to act on it.
- The only commands you hand the user are a sign-in command (Q1) and, if the installer asks for it, one `sudo loginctl enable-linger` command. Run everything else yourself.
- Never repeat, print, or log the agent API key once the user gives it to you.
- Never ask for a user or human API key. Only the agent API key from the Band website is needed.

## Shell rules

- Each command may run in a fresh shell with no terminal. Start every command with `export PATH="$HOME/.local/bin:$PATH";`. Never run anything that waits for keyboard input.
- When a command fails, read the error, fix the cause, and run it again. The installer's error messages name the fix.
- `config.example.yaml` in this repository explains every setting.

## Part 1: Prepare the machine (no questions)

**Access.** The install writes outside the current folder and downloads packages:

```bash
export PATH="$HOME/.local/bin:$PATH"; mkdir -p "$HOME/.local/share" "$HOME/.cache" "$HOME/.config" && d1=$(mktemp -d -p "$HOME/.local/share") && d2=$(mktemp -d -p "$HOME/.cache") && rmdir "$d1" "$d2" && curl -fsS -o /dev/null https://github.com && echo access-ok
```

If `access-ok` does not print, run it again with escalated permissions. If you cannot escalate, or the request is refused, send the user this and wait:

> I need permission to install outside this folder and use the network. In Codex, type `/permissions` and choose **Full Access**, or **Ask for approval** to approve each step, then tell me to continue. In Claude Code, approve the commands as they come up.

**Machine check.**

```bash
export PATH="$HOME/.local/bin:$PATH"; uname -s; id -u; command -v git curl systemctl; command -v codex; [ "$(id -u)" = 0 ] || (systemctl --user show-environment >/dev/null 2>&1 && echo user-systemd-ok)
```

You need Linux with `git`, `curl`, and `systemctl`. When the user is not root (`id -u` is not `0`), `user-systemd-ok` must also print. Without systemd, add `--service none` to the install command in Part 3, and tell the user that the agent runs only while `band-agentd run` is running.

**Install band-agentd.**

```bash
export PATH="$HOME/.local/bin:$PATH"; command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
export PATH="$HOME/.local/bin:$PATH"; SRC="$HOME/.local/share/band-agentd/src"; if [ -d "$SRC/.git" ]; then git -C "$SRC" pull --ff-only; else git clone https://github.com/darvell-thenvoi/band-agentd "$SRC"; fi; uv tool install --force "${SRC}[codex,claude]" && band-agentd --help >/dev/null && echo band-agentd-ok
```

Keep the braces in `"${SRC}[codex,claude]"`, because zsh would otherwise read `[codex,claude]` as an array subscript. A copy cloned elsewhere to read this file can stay where it is.

## Part 2: The conversation

### Q1. Codex or Claude?

> band-agentd is installed. Want to set up a Band agent now? It can run on **Codex** or **Claude**. You're using Codex right now, so Codex is ready to go. Which one?

Adjust the last sentence to match the tool the user is talking to you through. If they don't want an agent now, say that they can ask you to set one up any time, and stop.

Then check the choice yourself:

- **Codex:** `command -v codex && codex login status`. If `codex` is missing, install it with `npm install -g @openai/codex`. If it is not signed in, ask the user to run `codex login --device-auth` in another terminal on this machine and tell you when it's done.
- **Claude:** the Claude CLI comes with band-agentd. `band-agentd models --adapter claude` in Q3 reports whether it is signed in. If it isn't, give the user the sign-in command from the error and wait.

### Q2. Name and job

> What should we call your agent, and what will it do? For example: "Payments Helper: fixes bugs and reviews changes in the payments repo."

From the answer, work out:

- **Name** for Band: 3 to 24 characters, using only letters, numbers, and spaces. If theirs doesn't fit, shorten it and mention the change.
- **Description** for Band: one sentence, at least 10 characters, saying what the agent does.
- **Instructions:** the job, in their words, written as instructions to the agent.
- **Working folder:** the repository or folder it works in. If the user named a project, look for it, for example with `find ~ /srv /opt -maxdepth 3 -name .git -type d 2>/dev/null`, and confirm the match in one line. If they named nothing, ask once: "Which folder should it work in? I'd suggest `<path>`." Suggest the current folder if it is a git repository.
- **Service name**, which you keep to yourself: the agent name in lowercase with hyphens, for example `payments-helper`. Add a number if `~/.config/band-agentd/<name>.yaml` already exists.

### Q3. Model

List the models this machine's login offers:

```bash
export PATH="$HOME/.local/bin:$PATH"; band-agentd models --adapter <codex|claude>
```

> Which model should it use? I'd go with **gpt-6.1-sol** on **medium** reasoning. Here's what's available:
> (each model on one line: id, short description, reasoning levels)

For Codex, suggest `gpt-6.1-sol` with `medium` when the list has it. Otherwise, and for Claude, suggest the model marked `*` with `medium`. Accept only models and reasoning levels from the list.

### Q4. How much freedom?

> How much should it be allowed to do on this machine?
> 1. **Full access** (suggested): runs any command and edits any file without asking. Best for a machine dedicated to the agent.
> 2. **Ask first**: works freely in its own folder and asks in the Band room before anything else, like installing packages or committing.
> 3. **Read only**: reads and answers questions, but changes nothing.

For Claude, describe **Ask first** as "asks in the Band room before every action, including reading files", because that is how Claude's approvals work. Map the answer to `--access full`, `--access ask`, or `--access read-only`.

### Q5. Create the agent on Band

> Last step on your side: create the agent on Band.
> 1. Open https://app.band.ai/agents/create
> 2. **Agent name:** `<name>`
> 3. **Description:** `<description>`
> 4. Click **Connect Agent**.
> 5. Paste the **ID** and **API Key** it shows you here. The key is only shown once.

The ID is a UUID. If the user pastes a handle such as `@name/agent`, ask for the ID instead. If they lost the key, they can generate a new one from the agent's menu on the website.

## Part 3: Install and verify (no questions)

```bash
export PATH="$HOME/.local/bin:$PATH"; printf '%s\n' '<API key>' | band-agentd install \
  --adapter <codex|claude> \
  --cwd <working folder> \
  --agent-id <ID> \
  --api-key-stdin \
  --name '<name>' \
  --description '<description>' \
  --instructions '<instructions>' \
  --model <model> \
  --reasoning-effort <level> \
  --access <full|ask|read-only> \
  --unit <service name>
```

The installer checks the sign-in, model, and credentials with Band before it writes anything. It saves the settings to `~/.config/band-agentd/<service name>.yaml`, then installs and starts the service. If it fails, fix the cause and rerun the command with `--force` added. If it prints a lingering warning, give the user the `sudo loginctl enable-linger ...` command it shows. Without lingering, the agent stops when the user logs out.

Confirm the agent is online. Leave out `--user` when installed as root:

```bash
export PATH="$HOME/.local/bin:$PATH"; sleep 10; systemctl --user is-active <service name>; journalctl --user -u <service name> -n 60 --no-pager | grep -E 'Agent started|ERROR|Error|Traceback'
```

`active` plus `Agent started` means the agent is online. If not, read the full log with `journalctl --user -u <service name> -n 200 --no-pager`, fix the cause, and restart with `systemctl --user restart <service name>`. Then check again.

| Log shows | Fix |
| --- | --- |
| `401` or `rejected the agent API key` | The key was mistyped or replaced. Ask for the key again, or a new one from the agent's menu. |
| `Codex is not signed in` or `codex: not found` | The service runs as this user. Sign Codex in as this user, then restart. |
| `runtime.cwd is not a directory` | Fix `runtime.cwd` in the settings file. Saving restarts the agent. |
| Repeated restarts with a Python traceback | Read the traceback. If it isn't a settings problem, report it with the log lines. |

## Part 4: Wrap up

Tell the user, briefly:

> **<name>** is live on Band. To use it, open or create a room at app.band.ai, add <name>, and @mention it with what you need. It only responds when it is mentioned, and it can work in several rooms at once, all in `<working folder>`.
>
> To change it, edit `~/.config/band-agentd/<service name>.yaml`; it restarts on its own when you save. To add more agents or change one later, open Codex or Claude in `~/.local/share/band-agentd/src` and ask; the instructions there tell it what to do.
>
> To remove it from this machine, run `band-agentd remove <service name>`. That stops it and deletes its settings but leaves `<working folder>` alone. To delete it from Band too, use its menu on app.band.ai.

With **Ask first**, add: "When it needs permission, it asks in the room. Reply `/approve <id>` or `/decline <id>`." For a Claude agent with **Ask first**, also add: "Claude asks before every action, including reading files. If that gets noisy, I can switch it to full access."

Then ask: "Want to set up another agent?" If yes, go back to Q1.

## Later requests

A user may open Codex or Claude in `~/.local/share/band-agentd/src` later to add, change, or remove agents.

- **Find the agents:** `ls ~/.config/band-agentd/`. Each `<service name>.yaml` is one agent.
- **Add an agent:** run the conversation from Q1. Part 1 only needs `git -C ~/.local/share/band-agentd/src pull --ff-only` and the `uv tool install` command, to pick up updates.
- **Change an agent:** edit its settings file. Saving restarts the agent within a second. `config.example.yaml` explains each field. Common changes are `runtime.instructions`, `runtime.model` and `runtime.reasoning_effort` (choices from `band-agentd models --adapter <codex|claude>`), and access: `runtime.yolo: true` is full access, and `false` with `approval_mode: manual` is ask first.
- **Separate checkouts per room:** if the user wants rooms not to share files, set `runtime.workspace: worktree`. Each room then works in its own git worktree on a branch named `band/<room-id>`. The working folder must be in a git repository with at least one commit.
- **Remove an agent:** `band-agentd remove <service name>`. Tell the user that its working folder is untouched and that the agent still exists on Band until they delete it from its menu on app.band.ai.
- **Status and logs:** `systemctl --user status <service name>` and `journalctl --user -u <service name> -f`, without `--user` when installed as root.
