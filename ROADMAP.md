# Roadmap

Planned features. The numbers are the ones from the comparison with [herdr](https://github.com/herdrdev/herdr). Desktop notifications are not planned: Claude Code can send them natively (hooks, `preferredNotifChannel`).

## 5. Search and state filters

- `/` opens a search line at the bottom of the sidebar. It filters agents by name, window, session, branch and path, case-insensitive, while you type. `Enter` keeps the filter, `Esc` clears it.
- Filter keys outside the search: `w` waiting (red), `d` done (green), `b` busy (working), `a` all. The active filter shows in the title line.
- The filter is per sidebar pane (local state), not a tmux option, so two clients can use different filters.
- The numbers `1`–`9` and `j`/`k` work on the filtered list.

## 6. Resume agents after a tmux restart

The user runs tmux-resurrect and tmux-continuum. After a restore, a pane that ran Claude Code comes back as a plain shell.

- The hook stores the Claude Code session id on `SessionStart` as the pane option `@agent_session_id`, together with the cwd. Skip subagent events (`agent_id` in the hook input), like herdr does.
- Save the mapping (pane position `session:window.pane` → session id, cwd) in a file next to the resurrect save, for example with a `@resurrect-hook-post-save-all` hook. Pane options do not survive a tmux restart.
- After the restore (`@resurrect-hook-post-restore-all`), run `claude --resume <id>` in each matching pane that is at a shell prompt (check `pane_current_command`).
- Do nothing for panes that are not at a shell prompt, and for ids whose transcript file no longer exists.
- Option to turn it off: `@agent_sidebar_resume off`.

## 3. Worktrees from the sidebar

- `W` asks for a branch name (tmux `command-prompt`). It runs `git worktree add` in the repo of the selected agent: an existing local branch is checked out, otherwise the branch is created from the current `HEAD`.
- Checkout directory: `@agent_sidebar_worktree_dir`, default `<repo>/../<repo>-worktrees/<branch-slug>` (sibling directory, so editors do not index it inside the repo).
- It opens a new tmux window after the source agent's window, in the same session, starts `claude` there and selects the new agent in the sidebar.
- `O` lists the existing worktrees of the repo (tmux `display-menu`) and opens a window in the chosen one. A worktree that already has an agent window is focused instead.
- `D` on a linked worktree agent: `git worktree remove` (asks with `confirm-before`). If git refuses because of changes, ask again before `--force`. Never delete the branch.

## 4. Git status

- Show ahead/behind and local changes next to the branch: `⎇ main ↑2 ↓1 ●3`.
- One `git status --porcelain=v2 --branch` per repo in the worker thread, cached like `git_info` (TTL), never in the drawing loop.
- Agents in the same repo share one result.

## 2. Sound

- Play a sound when an agent changes to waiting (red) or done (green), but not for the agent in the window you look at.
- Detect the change in `refresh_live` (the place that already knows the transitions), only in the visible sidebar, so one change plays one sound.
- `@agent_sidebar_sound on|off`, `@agent_sidebar_sound_waiting <file>`, `@agent_sidebar_sound_done <file>`. Play with `paplay`, `pw-play` or `aplay` (first one found), in the background.

## Lessons from herdr

- **Bounded process scans.** herdr limits the `/proc` work per pane (number of processes, task entries and bytes read). Our BFS has a depth limit only. Add a process count limit.
- **Foreground process group.** herdr reads `tpgid` from `/proc/<pid>/stat` to find the job in the foreground of the terminal. This is more exact than "any `claude` process in the tree" (for example a `claude` started in the background of a shell).
- **Subagent hook events.** herdr ignores Claude Code hook events that have `agent_id` (subagents). Check if our hook must do the same for `Stop` / `Notification`.
- **State is separate from drawing.** herdr keeps state as plain data and makes rendering a pure function of it. That makes the state logic testable without a terminal. A Rust port is a good moment to do this.
- **Multiplicative paths.** herdr reviews every change in the per-tick and per-pane paths for its cost × panes × clients. Our rule "no process spawns on a normal switch" is the same idea. Keep it for every new feature (git status, search).
