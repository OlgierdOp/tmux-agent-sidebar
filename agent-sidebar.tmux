# tmux agent sidebar. Load it from ~/.tmux.conf:
#   source-file /path/to/tmux-agent-sidebar/agent-sidebar.tmux
set -gF @agent_sidebar_dir "#{d:current_file}"

# Selection background (xterm-256 color). Pick one live with `c` in the sidebar.
# set -g @agent_sidebar_bg 60

# prefix + a   -> show/hide the sidebar (in every window, shared state)
bind-key a run-shell -b "python3 #{@agent_sidebar_dir}/agent_sidebar.py toggle"
# prefix + Tab -> go to the agent that is waiting (red first, then green)
bind-key Tab run-shell -b "python3 #{@agent_sidebar_dir}/agent_sidebar.py next"

# On a window or session switch:
# - a window without a sidebar (new, or from another session) gets one,
# - a window with a sidebar gets F12, so the sidebar redraws at once.
# tmux evaluates the conditions and `run-shell -C` runs a tmux command, so a
# normal switch starts no process.
set-hook -g session-window-changed[42] {
  if -F "#{@agent_sidebar_on}" {
    if -F "#{==:#{P:#{?#{@agent_sidebar},x,}},}" {
      run-shell -b "python3 #{@agent_sidebar_dir}/agent_sidebar.py ensure #{window_id}"
    } {
      run-shell -C "send-keys -t #{P:#{?#{@agent_sidebar},#{pane_id},}} F12"
    }
  }
}
set-hook -g client-session-changed[42] {
  if -F "#{@agent_sidebar_on}" {
    if -F "#{==:#{P:#{?#{@agent_sidebar},x,}},}" {
      run-shell -b "python3 #{@agent_sidebar_dir}/agent_sidebar.py ensure #{window_id}"
    } {
      run-shell -C "send-keys -t #{P:#{?#{@agent_sidebar},#{pane_id},}} F12"
    }
  }
}
set-hook -g after-new-window[42] {
  if -F "#{&&:#{@agent_sidebar_on},#{==:#{P:#{?#{@agent_sidebar},x,}},}}" {
    run-shell -b "python3 #{@agent_sidebar_dir}/agent_sidebar.py ensure #{window_id}"
  }
}
