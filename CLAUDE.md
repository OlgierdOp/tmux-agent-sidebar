# CLAUDE.md

## Project

tmux agent sidebar: a tmux sidebar that lists the Claude Code agents running in tmux panes. It shows each agent's status, branch, worktree and token count. See `README.md` for features and architecture.

- `agent_sidebar.py`: curses TUI (Python 3, standard library only) and the `toggle` / `ensure` / `next` commands.
- `hooks/claude-hook.sh`: Claude Code hook. It writes `@agent_status`, `@agent_ts` and `@agent_transcript` as tmux pane options.
- `agent-sidebar.tmux`: tmux key bindings and hooks. The hooks use index `[42]`.
- `install.sh`: idempotent installer for `~/.claude/settings.json` and `~/.tmux.conf`.

## Rules

- **Keep `README.md` in sync with the code.** When you change behavior, keys, statuses, options, files, requirements or installation steps, update the matching README section in the same change. Before you finish a task, compare the README with the code:
  - key tables (the `handle_key` method and `agent-sidebar.tmux`),
  - the status table (`STATUS`),
  - the configuration table,
  - "How it works",
  - the "Files" table.
- Write all code, comments, UI strings, docs and commit messages in English.
- Put UI strings in `STRINGS` (keyed by `LANG`). Do not hard-code user-visible text.
- Use the Python standard library only. Do not add dependencies.
- Keep a normal window switch free of process spawns. The tmux hooks must check their condition in tmux formats before they call `run-shell`.
- Store shared sidebar state in global tmux options (`@agent_sidebar_*`), not in files.

## Testing

Test on a separate tmux server. Do not touch the user's real tmux server or config:

```bash
unset TMUX
tmux -L agtest -f /dev/null new-session -d -s agents ...
tmux -L agtest source-file ./agent-sidebar.tmux
# hooks need an attached client:
tmux -L agouter -f /dev/null new-session -d "env -u TMUX tmux -L agtest attach"
export TMUX="$(tmux -L agtest display -p '#{socket_path}'),1,0"
```

- A copy of `sleep` named `claude` works as a fake agent process.
- To fake hook events, pipe JSON into the hook with `TMUX_PANE` set:

  ```bash
  echo '{"hook_event_name":"Stop"}' | TMUX_PANE=%1 hooks/claude-hook.sh
  ```

- Check the rendered sidebar with `tmux capture-pane -p [-e]`.
- Kill both test servers when you finish.
