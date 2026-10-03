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
━━ agents ●1 ◐1 ━━━━━━━━━━━━━━━━━━━━━━━━━
 ◓ 1 auth                           142k
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
| `J` / `K`       | Move the selected agent down / up (swaps the tmux windows). At the edge of a session: move the whole session. |
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

Agents are grouped by tmux session. The home session is the session where you turned the sidebar on, and it is at the top by default.

To change the order, select an agent and press `J` (down) or `K` (up):

- Inside a session, the agent swaps places with the next or previous agent. The sidebar swaps the tmux windows (`swap-window`), so the window numbers in the tmux status bar change too. You stay in the window you look at. Two agents in one window swap panes.
- On the last agent of a session, `J` moves the whole session down. On the first agent, `K` moves it up. All sidebars use the same session order. It is stored in `@agent_sidebar_order` until tmux restarts. Sessions that are not in the order yet (new sessions) go after the others.

The agent numbers (`1`–`9`) always follow the order in the list.

### Statuses

| Symbol      | Meaning |
|-------------|---------|
| `●` red     | Waiting for you to accept: a permission prompt or a question |
| `●` green   | Finished, and you did not look at it yet. It turns idle when you show the agent. |
| `◐` yellow  | Working |
| `○` gray    | Idle. Also after you stop the agent (`Esc`, `Ctrl+C`) or reject a permission prompt. |
| `?`         | No hook data yet (for example, a session started before the installation) |

## Configuration

| Setting | Where | Default |
|---------|-------|---------|
| Selection background | `set -g @agent_sidebar_bg N` in `agent-sidebar.tmux` (xterm-256 color number) | `23` |
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
  - `@agent_sidebar_order`
  - `@agent_sidebar_gen` (changes when `J`/`K` swaps windows, so the other sidebars collect the data again)
- **Fast selection sync.** A selection change sends `F12` to the other sidebar panes, so they redraw at once. `Enter` waits (max ~150 ms) until the target window's sidebar has drawn the new selection, then it switches the window.
- **Window, session and pane switches.** The tmux hooks `session-window-changed`, `client-session-changed`, `after-select-pane` and `after-new-window` do two things:
  - they add a sidebar to a window on the first visit,
  - they send `F12` to the sidebar of the window you switch to, so it redraws at once (a few ms).

  tmux evaluates the conditions itself, and `run-shell -C` runs a tmux command, so a normal switch starts no process.
- **Reliable selection follow.** The visible sidebar compares the current window and active pane with the last pair it handled (`@agent_sidebar_focus`). It compares states, not events, so fast switching cannot make it miss a change. Visibility comes from `window_active_clients`, because tmux updates `session_attached` lazily.
- **Non-blocking UI.** A worker thread collects the agent data (process tree, git, tokens). The main loop only handles keys, `F12` and drawing, so it never waits for the data.
- **Agent detection.** The sidebar reads `tmux list-panes -a` and the process tree of each pane (`/proc/PID/task/TID/children`, with a full `/proc` scan as fallback). Any pane with a `claude` process in it is an agent.
- **Status.** Two sources:
  - Claude Code writes the state of each session (`busy`, `waiting`, `idle`) to `~/.claude/sessions/<pid>.json`. The sidebar finds the `claude` process of the pane and reads this file. When the pane runs only a client of a background session (`parkedJobId`), the sidebar reads the file of the background session (`jobId`). The file is correct at once, also after `Esc`, `Ctrl+C` or a rejected permission prompt, when no hook runs.
  - Every 0.1 s each sidebar checks these files (only a `stat` when nothing changed), so a status change shows in about 50 ms.
  - When a turn ends (`busy` → `idle`), the last message of the transcript tells how. An assistant reply that ended the turn means "finished": green, or idle when you look at the agent. Your prompt or `[Request interrupted by user]` at the end means you stopped it: idle.
  - `hooks/claude-hook.sh` runs on Claude Code hook events. It stores `@agent_status`, `@agent_ts` and `@agent_transcript` as tmux pane options. Its `Stop` event also sets "done". No hook runs for a background session.
  - Only a permission prompt or a question makes the dot red. A late notification after the turn ended does not.
  - Without a session file (older Claude Code), the sidebar uses the hook status. It sets idle when the transcript ends with `[Request interrupted by user]`, or when the `idle_prompt` notification comes (after about 60 s).
- **Tokens.** The context size comes from the `usage` of the last assistant message in the session transcript (input + cache + output tokens).
- **Name.** The name you give with `n`, else the window name. When tmux names the window automatically (after the command of the active pane), the sidebar uses the repo or directory name.
- **Git.** The sidebar runs `git rev-parse` in the agent's working directory. `[wt]` marks a linked worktree.
- **Refresh.** The visible sidebar refreshes its data every 1 s, hidden ones every 5 s. As a safety net, the visible sidebar also polls tmux state every 1 s (hidden: 2 s).

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
