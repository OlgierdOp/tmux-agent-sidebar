# tmux agent sidebar

A sidebar for tmux that lists every [Claude Code](https://claude.com/claude-code) agent running in your tmux panes. For each agent it shows:

- the status (working, waiting for you, finished, idle),
- the git branch,
- the worktree (linked git worktrees are marked),
- the context size in tokens.

You can move between agents with `j`/`k` and show an agent's window with `Enter`. The cursor stays in the sidebar while you do this.

```
 AGENTS ●1 ●1 ◐1
─────────────────────────────────────────
━━ agents ◆ ●1 ◐1 ━━━━━━━━━━━━━━━━━━━━━━━
▶◓ 1 auth                           142k
   ⎇ main
   ⌂ ~/repos/app
 ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
 ● 2 login                           38k
   ⎇ feat/login
   ⊕ ~/repos/app-login [wt]
 ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
━━ other ●1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ● 3 api                            211k
   ⎇ fix/timeout
   ⌂ ~/repos/api
```

## Requirements

- Linux (the agent detection reads `/proc`)
- tmux 3.2 or later (tested with 3.4)
- Python 3.8 or later (standard library only)
- `jq` (used by the Claude Code hook)
- Claude Code

A 256-color terminal is recommended.

## Installation

```bash
git clone https://github.com/OlgierdOp/tmux-agent-sidebar.git
cd tmux-agent-sidebar
./install.sh
```

`install.sh` does two things:

1. It adds `hooks/claude-hook.sh` to the hooks in `~/.claude/settings.json`.
2. It adds `source-file .../agent-sidebar.tmux` to `~/.tmux.conf`. The line goes before the TPM init line, if you have one.

Before it changes a file, the script makes a backup (`*.bak.<timestamp>`). You can run it more than once. Running Claude Code sessions pick up the new hooks on their next event.

### Manual installation

1. Add this line to `~/.tmux.conf`:

   ```tmux
   source-file /path/to/tmux-agent-sidebar/agent-sidebar.tmux
   ```

2. Register `hooks/claude-hook.sh` as a `command` hook in `~/.claude/settings.json` for these events:
   - `SessionStart`
   - `UserPromptSubmit`
   - `PreToolUse`
   - `PostToolUse`
   - `Notification`
   - `PermissionRequest`
   - `Stop`
   - `SessionEnd`

## Usage

| Key          | Action |
|--------------|--------|
| `prefix a`   | Show/hide the sidebar in all windows |
| `prefix Tab` | Go into the agent that waits for you (red first, then green, current session first) |

Keys in the sidebar:

| Key             | Action |
|-----------------|--------|
| `j` / `k`       | Move the selection |
| `g` / `G`       | First / last agent |
| `Enter` / `o`   | Show the agent's window. The cursor stays in the sidebar. |
| `i`             | Go into the agent's pane |
| `1`–`9`         | Show the agent with this number |
| `Tab`           | Select the next agent that waits for you |
| `s`             | Show only the home session / all sessions |
| `n`             | Give the agent a name |
| `c`             | Next selection background color (live preview) |
| `r`             | Refresh git data |
| `q`             | Close this sidebar pane |
| mouse click     | Show the agent's window |

When you show an agent with `Enter`, the agent becomes the last active pane in its window. Your normal pane navigation (for example `Ctrl+l` with vim-tmux-navigator, or `prefix ;`) goes into it.

The selection follows you. If you move to another agent with tmux keys or a script (`select-window`, `select-pane`), the sidebar selects that agent.

### Sessions

Agents are grouped by tmux session. The home session is the session where you turned the sidebar on, and it is always at the top. `◆` marks the session of the window you are looking at.

### Statuses

| Symbol      | Meaning |
|-------------|---------|
| `●` red     | Waiting for you: a permission prompt or a question |
| `●` green   | Finished, and you did not look at it yet. It turns idle when you show the agent. |
| `◐` yellow  | Working |
| `○` gray    | Idle |
| `?`         | No hook data yet (for example, a session started before the installation) |

## Configuration

| Setting | Where | Default |
|---------|-------|---------|
| Selection background | `set -g @agent_sidebar_bg N` in `agent-sidebar.tmux` (xterm-256 color number) | `60` |
| Sidebar width | `AGENT_SIDEBAR_WIDTH` environment variable | `42` |
| UI language | `LANG` and `STRINGS` at the top of `agent_sidebar.py` (only `en` for now) | `en` |
| Key bindings | `agent-sidebar.tmux` | `prefix a`, `prefix Tab` |

To choose a background color, press `c` in the sidebar until you like the color. The number shows in the top-right corner for 3 seconds. Write it into `agent-sidebar.tmux` to keep it after a tmux restart.

## How it works

- **One sidebar pane per window.** A switch between windows does not move or resize panes, so nothing flickers. The panes share their state through global tmux options:
  - `@agent_sidebar_on`
  - `@agent_sidebar_sel`
  - `@agent_sidebar_only`
  - `@agent_sidebar_home`
  - `@agent_sidebar_bg`
- **Fast selection sync.** A selection change sends `F12` to the other sidebar panes, so they redraw at once. `Enter` waits (max ~150 ms) until the target window's sidebar has drawn the new selection, then it switches the window.
- **New windows.** The tmux hooks `session-window-changed`, `client-session-changed` and `after-new-window` add a sidebar to a window on the first visit. tmux evaluates the condition, so a normal window switch starts no process.
- **Agent detection.** The sidebar reads `tmux list-panes -a` and the process tree in `/proc`. Any pane with a `claude` process in it is an agent.
- **Status.** `hooks/claude-hook.sh` runs on Claude Code hook events. It stores `@agent_status`, `@agent_ts` and `@agent_transcript` as tmux pane options. There are no state files, and the data goes away with the pane.
- **Tokens.** The context size comes from the `usage` of the last assistant message in the session transcript (input + cache + output tokens).
- **Git.** The sidebar runs `git rev-parse` in the agent's working directory. `[wt]` marks a linked worktree.
- **Hidden panes** refresh their data every 5 s. The visible pane refreshes every 1 s and checks focus changes every 250 ms.

## Files

| File | Purpose |
|------|---------|
| `agent_sidebar.py` | Sidebar TUI and the `toggle`, `ensure` and `next` commands |
| `hooks/claude-hook.sh` | Claude Code hook that writes the agent status into tmux |
| `agent-sidebar.tmux` | tmux key bindings and hooks |
| `install.sh` | Installer |

## Uninstall

1. Remove the `source-file .../agent-sidebar.tmux` line from `~/.tmux.conf`.
2. Remove the `claude-hook.sh` entries from `~/.claude/settings.json`.
3. Restart tmux, or unbind `prefix a` / `prefix Tab` and remove the `[42]` hooks by hand.

## License

MIT
