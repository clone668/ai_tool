# Security

## Deployment assumptions

AI Tool is designed for a trusted private network. The production service listens on TCP port `19090` and requires administrator authentication. Public Internet exposure is not supported without an HTTPS reverse proxy and `AI_TOOL_COOKIE_SECURE=1`.

The web process runs as the unprivileged `ai-tool` user. The browser terminal uses a separate `ai-tool-shell` account that cannot invoke the privileged helper, and requires both a valid session cookie and an exact same-origin WebSocket handshake. Privileged operations go through the root-owned `/usr/local/libexec/ai-tool-ops` helper, which validates every action and argument and never executes a shell.

Only one authenticated browser terminal session can be active at a time. Terminal processes run in a dedicated controlling PTY; disconnecting the WebSocket or reaching the authenticated session expiry closes the PTY and invokes a no-argument privileged cleanup command for the fixed `ai-tool-shell` UID. This removes process-group escapes such as `nohup` and `setsid` without accepting a caller-supplied user or process ID.

Package removal blocks essential system packages. Service controls protect SSH, Docker, and AI Tool itself. Cleanup actions are fixed allowlisted operations; `/data` and Docker volumes are never removed automatically. Managed Nginx upstreams are limited to `127.0.0.1` and `localhost`.

Web discovery is read-only. It inspects active Nginx configuration, Docker-published TCP ports, and local listeners, then performs bounded HTTP probes. Existing Nginx files remain externally owned and cannot be edited or deleted through the discovery view. Only an explicit administrator action can create a new configuration under the AI Tool-owned Nginx directories.

Software removal, cleanup, and optimization endpoints require a short-lived single-use confirmation token issued with the corresponding preview. Replayed, expired, or mismatched confirmations are rejected and audited.

## Credentials

- Never commit `AI_TOOL_PASSWORD_HASH`, SSH passwords, API tokens, `.env` files, or application logs.
- Use a unique administrator password of at least 12 characters.
- Prefer SSH key authentication for server maintenance.
- Rotate credentials immediately if they are exposed in chat, shell history, logs, or source control.

## Reporting

Report security issues privately to the repository owner. Include the affected version, reproduction steps, and impact; do not include live credentials or production logs.
