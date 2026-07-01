#!/bin/bash
# PostToolUse hook: TodoWriteが一定回数使われないまま作業ツール(Bash/Edit/Write)が
# 続いた場合、進行状況メモを促すリマインドをモデルに注入する（ブロックはしない）。
set -euo pipefail

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
SESSION=$(echo "$INPUT" | jq -r '.session_id // "default"')

STATE_DIR="/tmp/claude-dive-log-todo-state"
mkdir -p "$STATE_DIR"
COUNT_FILE="$STATE_DIR/$SESSION.count"

if [ "$TOOL" = "TodoWrite" ]; then
  echo 0 > "$COUNT_FILE"
  exit 0
fi

case "$TOOL" in
  Bash|Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

COUNT=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNT_FILE"

THRESHOLD=8
if [ "$COUNT" -ge "$THRESHOLD" ]; then
  echo 0 > "$COUNT_FILE"
  echo '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "作業ツールの呼び出しが続いています。TodoWriteでタスクリストを更新するか、進行状況をメモしてください。"}}'
fi
exit 0
