#!/usr/bin/env bash
# Claude Code hook -> stores the agent status as a tmux pane option (@agent_status).
# Runs for: SessionStart UserPromptSubmit PreToolUse PostToolUse
#           Notification PermissionRequest Stop SessionEnd
[ -n "$TMUX" ] && [ -n "$TMUX_PANE" ] || exit 0

input=$(cat)
IFS=$'\x1f' read -r event transcript < <(
  jq -r '[.hook_event_name // "", .transcript_path // ""] | join("\u001f")' <<<"$input" 2>/dev/null)
pane="$TMUX_PANE"

set_status() {
  tmux set-option -p -t "$pane" @agent_status "$1" \; \
       set-option -p -t "$pane" @agent_ts "$(date +%s)" 2>/dev/null
}

IFS=$'\x1f' read -r current cur_transcript < <(
  tmux display-message -p -t "$pane" $'#{@agent_status}\x1f#{@agent_transcript}' 2>/dev/null)
# transcript path -> the sidebar reads token usage from it (it changes after /clear)
if [ -n "$transcript" ] && [ "$transcript" != "$cur_transcript" ]; then
  tmux set-option -p -t "$pane" @agent_transcript "$transcript" 2>/dev/null
fi

case "$event" in
  SessionStart)                         set_status idle ;;
  UserPromptSubmit|PreToolUse|PostToolUse)
    [ "$current" = working ] || set_status working ;;
  PermissionRequest)                    set_status waiting ;;
  Notification)
    type=$(jq -r '.notification_type // empty' <<<"$input")
    msg=$(jq -r '.message // empty' <<<"$input")
    # "idle" after finished work keeps "done". Anything else (permission, question) -> waiting
    if [ "$type" = idle_prompt ] || [[ "$msg" == *"waiting for your input"* ]]; then
      [ "$current" = done ] || [ "$current" = idle ] || set_status waiting
    else
      set_status waiting
    fi ;;
  Stop)
    # if you are looking at this pane right now, do not highlight it
    seen=$(tmux display-message -p -t "$pane" \
      '#{&&:#{pane_active},#{window_active_clients}}' 2>/dev/null)
    if [ "$seen" = 1 ]; then set_status idle; else set_status done; fi ;;
  SessionEnd)
    tmux set-option -p -u -t "$pane" @agent_status \; \
         set-option -p -u -t "$pane" @agent_ts 2>/dev/null ;;
esac
exit 0
