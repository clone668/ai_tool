#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/data/ai-tool"
DATA_DIR="/data/ai-tool-data"
TERMINAL_DIR="/data/ai-tool-terminal"
CONFIG_DIR="/etc/ai-tool"
SERVICE_NAME="ai-tool.service"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh must run as root" >&2
  exit 1
fi

if [[ "${REPO_DIR}" != "${APP_DIR}" ]]; then
  echo "repository must be checked out at ${APP_DIR}" >&2
  exit 1
fi

if [[ ! -d /data || ! -w /data ]]; then
  echo "/data is unavailable" >&2
  exit 1
fi

for command in python3 npm systemctl sudo visudo curl; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "required command is missing: ${command}" >&2
    exit 1
  fi
done

if ! id ai-tool >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin ai-tool
fi
if ! id ai-tool-shell >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "${TERMINAL_DIR}" --shell /usr/sbin/nologin ai-tool-shell
fi

install -d -o root -g root -m 0755 "${CONFIG_DIR}"
install -d -o ai-tool -g ai-tool -m 0750 "${DATA_DIR}"
install -d -o ai-tool-shell -g ai-tool -m 0710 "${TERMINAL_DIR}"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "${APP_DIR}/requirements.txt"
npm --prefix "${APP_DIR}/frontend" ci --no-audit --no-fund
npm --prefix "${APP_DIR}/frontend" run build

install -o root -g root -m 0644 "${APP_DIR}/config/projects.json" "${CONFIG_DIR}/projects.json"
install -o root -g root -m 0755 "${APP_DIR}/deploy/ai_tool_ops.py" /usr/local/libexec/ai-tool-ops
install -o root -g root -m 0644 "${APP_DIR}/deploy/ai-tool.service" "/etc/systemd/system/${SERVICE_NAME}"
install -o root -g root -m 0440 "${APP_DIR}/deploy/ai-tool.sudoers" /etc/sudoers.d/ai-tool
visudo -cf /etc/sudoers.d/ai-tool >/dev/null

ENV_FILE="${CONFIG_DIR}/ai-tool.env"
if [[ -n "${AI_TOOL_ADMIN_PASSWORD:-}" ]]; then
  PASSWORD_HASH="$(AI_TOOL_PASSWORD_INPUT="${AI_TOOL_ADMIN_PASSWORD}" PYTHONPATH="${APP_DIR}/backend" "${APP_DIR}/.venv/bin/python" -c 'import os; from app.security import hash_password; print(hash_password(os.environ["AI_TOOL_PASSWORD_INPUT"]))')"
  umask 0077
  {
    printf 'AI_TOOL_CONFIG=%s\n' "${CONFIG_DIR}/projects.json"
    printf 'AI_TOOL_DATA_DIR=%s\n' "${DATA_DIR}"
    printf 'AI_TOOL_STATIC_DIR=%s\n' "${APP_DIR}/frontend/dist"
    printf 'AI_TOOL_OPS_HELPER=%s\n' "/usr/local/libexec/ai-tool-ops"
    printf 'AI_TOOL_PASSWORD_HASH=%s\n' "${PASSWORD_HASH}"
    printf 'AI_TOOL_SESSION_HOURS=%s\n' "12"
    printf 'AI_TOOL_COOKIE_SECURE=%s\n' "0"
    printf 'AI_TOOL_TERMINAL_ENABLED=%s\n' "1"
    printf 'AI_TOOL_TERMINAL_HOME=%s\n' "${TERMINAL_DIR}"
  } > "${ENV_FILE}"
  unset AI_TOOL_ADMIN_PASSWORD AI_TOOL_PASSWORD_INPUT PASSWORD_HASH
elif [[ ! -f "${ENV_FILE}" ]]; then
  echo "AI_TOOL_ADMIN_PASSWORD is required for the first installation" >&2
  exit 1
fi
if ! grep -q '^AI_TOOL_TERMINAL_ENABLED=' "${ENV_FILE}"; then
  printf 'AI_TOOL_TERMINAL_ENABLED=%s\n' "1" >> "${ENV_FILE}"
fi
if ! grep -q '^AI_TOOL_TERMINAL_HOME=' "${ENV_FILE}"; then
  printf 'AI_TOOL_TERMINAL_HOME=%s\n' "${TERMINAL_DIR}" >> "${ENV_FILE}"
fi
chown root:ai-tool "${ENV_FILE}"
chmod 0640 "${ENV_FILE}"

find "${APP_DIR}" -path "${APP_DIR}/.git" -prune -o -type d -exec chmod go-w {} +
find "${APP_DIR}" -path "${APP_DIR}/.git" -prune -o -type f -exec chmod go-w {} +

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

for _ in {1..20}; do
  if curl --fail --silent --show-error http://127.0.0.1:19090/api/health >/dev/null; then
    echo "AI Tool is available at http://$(hostname -I | awk '{print $1}'):19090"
    exit 0
  fi
  sleep 1
done

systemctl status "${SERVICE_NAME}" --no-pager >&2 || true
journalctl -u "${SERVICE_NAME}" -n 60 --no-pager >&2 || true
echo "AI Tool failed its startup health check" >&2
exit 1
