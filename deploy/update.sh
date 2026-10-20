#!/usr/bin/env bash
# Self-update runner for AI Tool. Executed by systemd-run as the transient
# ai-tool-update.service so it survives the ai-tool.service restart at the end.
set -uo pipefail

APP_DIR="/data/ai-tool"
STATE="/etc/ai-tool/update-state.json"
LOG="/var/log/ai-tool-update.log"

exec >>"${LOG}" 2>&1
echo "=== update started $(date -Is) ==="

write_state() {
  # write_state <status> <message>
  local status="$1" message="$2"
  local to_commit
  to_commit="$(git -c "safe.directory=${APP_DIR}" -C "${APP_DIR}" rev-parse HEAD 2>/dev/null || true)"
  python3 - "$STATE" "$status" "$message" "$to_commit" <<'PY'
import json, sys
from datetime import datetime, timezone

path, status, message, to_commit = sys.argv[1:5]
try:
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
except (OSError, ValueError):
    state = {}
state.update({
    "running": False,
    "status": status,
    "message": message,
    "to_commit": to_commit or None,
    "finished_at": datetime.now(timezone.utc).isoformat(),
})
with open(path, "w", encoding="utf-8") as handle:
    json.dump(state, handle, ensure_ascii=False)
    handle.write("\n")
PY
}

echo "--- git pull ---"
if ! git -c "safe.directory=${APP_DIR}" -C "${APP_DIR}" pull --ff-only; then
  echo "git pull failed"
  write_state "failed" "拉取代码失败，请检查网络和仓库状态"
  exit 1
fi

echo "--- install.sh ---"
if ! bash "${APP_DIR}/deploy/install.sh"; then
  echo "install.sh failed"
  write_state "failed" "安装或重启服务失败，请查看更新日志"
  exit 1
fi

echo "=== update finished $(date -Is) ==="
write_state "success" "更新完成，服务已重启"
exit 0
