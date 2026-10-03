#!/usr/bin/env bash
# Installs the Claude Code hooks (~/.claude/settings.json) and the tmux bindings (~/.tmux.conf).
# Idempotent: safe to run more than once. Makes backups before it changes a file.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$DIR/hooks/claude-hook.sh"
SETTINGS="$HOME/.claude/settings.json"
TMUX_CONF="$HOME/.tmux.conf"
SNIPPET="$DIR/agent-sidebar.tmux"

command -v jq >/dev/null || { echo "jq is required"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }

# --- Claude Code hooks
mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
cp "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d%H%M%S)"
tmp=$(mktemp)
jq --arg cmd "$HOOK" '
  def entry: {hooks: [{type: "command", command: $cmd, timeout: 5}]};
  .hooks //= {}
  | reduce ("SessionStart","UserPromptSubmit","PreToolUse","PostToolUse",
            "Notification","PermissionRequest","Stop","SessionEnd") as $ev (.;
      .hooks[$ev] = ((.hooks[$ev] // [])
                     | map(select(all(.hooks[]?; .command != $cmd)))
                     + [entry]))
' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
echo "✓ hooks added to $SETTINGS"

# --- tmux
LINE="source-file $SNIPPET"
if ! grep -qF "$LINE" "$TMUX_CONF" 2>/dev/null; then
  cp "$TMUX_CONF" "$TMUX_CONF.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
  if grep -q "^run '~/.tmux/plugins/tpm/tpm'" "$TMUX_CONF" 2>/dev/null; then
    # before the TPM init line, which must stay last
    sed -i "/^run '~\/.tmux\/plugins\/tpm\/tpm'/i # Agent sidebar\n$LINE\n" "$TMUX_CONF"
  else
    printf '\n# Agent sidebar\n%s\n' "$LINE" >> "$TMUX_CONF"
  fi
  echo "✓ added to $TMUX_CONF"
fi
if [ -n "${TMUX:-}" ]; then
  tmux source-file "$TMUX_CONF" && echo "✓ tmux config reloaded"
fi
echo "Done. Press prefix + a to show the sidebar."
