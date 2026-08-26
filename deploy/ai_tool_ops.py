#!/usr/bin/env python3
"""Root-owned allowlisted operations helper for AI Tool.

The web process can invoke only project/component/action combinations declared in
/etc/ai-tool/projects.json. No shell is used and no path is accepted from the caller.
"""

from __future__ import annotations

import argparse
import base64
import copy
import http.client
import json
import os
import platform
import pwd
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/etc/ai-tool/projects.json")
SYSTEMCTL = "/usr/bin/systemctl"
JOURNALCTL = "/usr/bin/journalctl"
DOCKER = "/usr/bin/docker"
RUNUSER = "/usr/sbin/runuser"
CRONTAB = "/usr/bin/crontab"
TAIL = "/usr/bin/tail"
ALLOWED_ACTIONS = {"start", "restart", "stop"}
APT_GET = "/usr/bin/apt-get"
APT_CACHE = "/usr/bin/apt-cache"
DPKG_QUERY = "/usr/bin/dpkg-query"
NGINX = "/usr/sbin/nginx"
PS = "/usr/bin/ps"
LSBLK = "/usr/bin/lsblk"
DF = "/usr/bin/df"
SS = "/usr/bin/ss"
WEB_STATE_PATH = Path("/etc/ai-tool/web-services.json")
WEB_BACKUP_DIR = Path("/etc/ai-tool/backups/web")
WEB_AVAILABLE_DIR = Path("/etc/nginx/ai-tool-sites-available")
WEB_ENABLED_DIR = Path("/etc/nginx/ai-tool-sites-enabled")
WEB_INCLUDE_PATH = Path("/etc/nginx/conf.d/ai-tool-managed.conf")
TERMINAL_USER = "ai-tool-shell"
TERMINAL_CLEANUP_GRACE_SECONDS = 1.0
NON_WEB_PORTS = {
    22,
    53,
    111,
    139,
    445,
    631,
    2049,
    3306,
    33060,
    5432,
    6379,
}
INTERNAL_WEB_PROCESSES = {"containerd"}
SERVICE_DISPLAY_NAMES = {"ai-tool.service": "AI Tool"}
PACKAGE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,127}(?::[a-z0-9-]+)?$")
UNIT_PATTERN = re.compile(r"^[A-Za-z0-9@_.:-]+\.(?:service|timer|socket|path)$")
CONTAINER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
WEB_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
DOMAIN_PATTERN = re.compile(r"^(?:\*\.)?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
PROTECTED_PACKAGES = {
    "apt",
    "bash",
    "base-files",
    "coreutils",
    "docker-ce",
    "docker.io",
    "dpkg",
    "init",
    "libc6",
    "login",
    "linux-generic",
    "linux-image-generic",
    "network-manager",
    "netplan.io",
    "openssh-client",
    "openssh-server",
    "python3",
    "snapd",
    "sudo",
    "systemd",
    "ubuntu-minimal",
    "ubuntu-standard",
}
PROTECTED_PACKAGE_PREFIXES = ("linux-headers-", "linux-image-", "linux-modules-")
PROTECTED_SNAPS = {"bare", "core", "core18", "core20", "core22", "core24", "snapd"}
PROTECTED_UNITS = {
    "NetworkManager.service",
    "ai-tool.service",
    "dbus.service",
    "docker.service",
    "docker.socket",
    "networking.service",
    "ssh.service",
    "ssh.socket",
    "sshd.service",
    "systemd-logind.service",
    "systemd-networkd.service",
}


class OpsFailure(RuntimeError):
    pass


def _owned_process_ids(uid: int) -> set[int]:
    process_ids: set[int] = set()
    try:
        entries = os.scandir("/proc")
    except OSError as exc:
        raise OpsFailure("process inventory is unavailable") from exc
    with entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat(follow_symlinks=False).st_uid != uid:
                    continue
                stat_value = Path(entry.path, "stat").read_text(
                    encoding="ascii", errors="replace"
                )
                state = stat_value.rsplit(")", 1)[1].strip().split(maxsplit=1)[0]
            except (IndexError, OSError):
                continue
            if state != "Z":
                process_ids.add(int(entry.name))
    return process_ids


def _signal_processes(process_ids: set[int], sig: signal.Signals) -> None:
    for process_id in process_ids:
        with suppress(ProcessLookupError):
            os.kill(process_id, sig)


def _terminate_uid_processes(uid: int) -> dict[str, int]:
    targeted = _owned_process_ids(uid)
    pending = set(targeted)
    _signal_processes(pending, signal.SIGTERM)
    deadline = time.monotonic() + TERMINAL_CLEANUP_GRACE_SECONDS
    empty_scans = 0
    while time.monotonic() < deadline:
        time.sleep(0.05)
        current = _owned_process_ids(uid)
        new_processes = current - targeted
        if new_processes:
            targeted.update(new_processes)
            _signal_processes(new_processes, signal.SIGTERM)
        pending = current
        empty_scans = empty_scans + 1 if not pending else 0
        if empty_scans >= 2:
            break

    killed = set(pending)
    _signal_processes(killed, signal.SIGKILL)
    kill_deadline = time.monotonic() + TERMINAL_CLEANUP_GRACE_SECONDS
    empty_scans = 0
    while killed and time.monotonic() < kill_deadline:
        time.sleep(0.05)
        pending = _owned_process_ids(uid)
        new_processes = pending - targeted
        if new_processes:
            targeted.update(new_processes)
            killed.update(new_processes)
            _signal_processes(new_processes, signal.SIGKILL)
        empty_scans = empty_scans + 1 if not pending else 0
        if empty_scans >= 2:
            break
    if pending:
        raise OpsFailure("terminal processes could not be fully terminated")
    return {"matched": len(targeted), "killed": len(killed), "remaining": 0}


def terminal_cleanup() -> dict[str, Any]:
    try:
        terminal_user = pwd.getpwnam(TERMINAL_USER)
    except KeyError as exc:
        raise OpsFailure("terminal system user does not exist") from exc
    if terminal_user.pw_uid <= 0:
        raise OpsFailure("terminal system user has an unsafe UID")
    result: dict[str, Any] = {"ok": True, "user": TERMINAL_USER}
    result.update(_terminate_uid_processes(terminal_user.pw_uid))
    return result


def run(
    command: list[str],
    timeout: int = 15,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
    if extra_env:
        environment.update(extra_env)
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OpsFailure(f"command failed: {command[0]}") from exc


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpsFailure("managed project configuration is unavailable") from exc
    if not isinstance(value, dict) or not isinstance(value.get("projects"), list):
        raise OpsFailure("managed project configuration is invalid")
    return value


def find_component(
    config: dict[str, Any], project_id: str, component_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    for project in config["projects"]:
        if project.get("id") != project_id:
            continue
        for component in project.get("components", []):
            if component.get("id") == component_id:
                return project, component
        break
    raise OpsFailure("project component is not managed")


def parse_properties(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def user_systemctl_prefix(user: str) -> list[str]:
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError as exc:
        raise OpsFailure("managed system user does not exist") from exc
    runtime_dir = f"/run/user/{uid}"
    return [
        RUNUSER,
        "-u",
        user,
        "--",
        "/usr/bin/env",
        f"XDG_RUNTIME_DIR={runtime_dir}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir}/bus",
        SYSTEMCTL,
        "--user",
    ]


def systemd_status(component: dict[str, Any]) -> dict[str, Any]:
    properties = [
        "ActiveState",
        "SubState",
        "MainPID",
        "MemoryCurrent",
        "ActiveEnterTimestamp",
        "LoadState",
    ]
    base = [SYSTEMCTL]
    if component["type"] == "user_systemd":
        base = user_systemctl_prefix(component["user"])
    result = run(
        base
        + [
            "show",
            component["service"],
            "--no-pager",
            *[f"--property={name}" for name in properties],
        ]
    )
    values = parse_properties(result.stdout)
    active = values.get("ActiveState") == "active"
    memory_value = values.get("MemoryCurrent", "")
    memory_bytes = int(memory_value) if memory_value.isdigit() else None
    if memory_bytes is not None and memory_bytes >= 2**63:
        memory_bytes = None
    return {
        "state": values.get("ActiveState", "unknown"),
        "substate": values.get("SubState", "unknown"),
        "healthy": active,
        "pid": int(values.get("MainPID", "0") or 0),
        "memory_bytes": memory_bytes,
        "since": values.get("ActiveEnterTimestamp") or None,
        "detail": values.get("LoadState", "unknown"),
    }


def compose_status(component: dict[str, Any]) -> dict[str, Any]:
    containers = component["containers"]
    result = run([DOCKER, "inspect", *containers])
    if result.returncode != 0:
        return {
            "state": "missing",
            "substate": "inspect failed",
            "healthy": False,
            "children": [],
            "detail": result.stderr.strip()[-500:],
        }
    try:
        inspected = json.loads(result.stdout)
    except json.JSONDecodeError:
        inspected = []
    by_name = {item.get("Name", "").lstrip("/"): item for item in inspected}
    children = []
    for name in containers:
        item = by_name.get(name, {})
        state = item.get("State", {})
        health = state.get("Health", {}).get("Status")
        running = bool(state.get("Running"))
        healthy = running and health not in {"unhealthy", "starting"}
        children.append(
            {
                "name": name,
                "state": state.get("Status", "missing"),
                "health": health,
                "healthy": healthy,
                "started_at": state.get("StartedAt") or None,
                "restart_count": item.get("RestartCount", 0),
            }
        )
    all_healthy = len(children) == len(containers) and all(child["healthy"] for child in children)
    any_running = any(child["state"] == "running" for child in children)
    return {
        "state": "running" if all_healthy else ("degraded" if any_running else "stopped"),
        "substate": f"{sum(child['healthy'] for child in children)}/{len(containers)} containers",
        "healthy": all_healthy,
        "children": children,
        "detail": component["compose_file"],
    }


def cron_status(component: dict[str, Any]) -> dict[str, Any]:
    result = run([CRONTAB, "-l"])
    present = component["command"] in result.stdout
    log_path = Path(component["log_path"])
    last_modified = None
    if log_path.exists():
        last_modified = datetime.fromtimestamp(log_path.stat().st_mtime, timezone.utc).isoformat()
    return {
        "state": "scheduled" if present else "missing",
        "substate": component["schedule"],
        "healthy": present,
        "since": last_modified,
        "detail": component["command"],
    }


def component_status(component: dict[str, Any]) -> dict[str, Any]:
    if component["type"] in {"systemd", "user_systemd"}:
        return systemd_status(component)
    if component["type"] == "compose":
        return compose_status(component)
    if component["type"] == "cron":
        return cron_status(component)
    raise OpsFailure("unsupported managed component type")


def tcp_check(check: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with socket.create_connection((check["host"], int(check["port"])), timeout=1.5):
            pass
        healthy = True
        detail = "connected"
    except OSError as exc:
        healthy = False
        detail = str(exc)
    return {
        "healthy": healthy,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "detail": detail,
    }


def http_check(check: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    request = urllib.request.Request(
        check["url"], headers={"User-Agent": "ai-tool-health/1.0", **check.get("headers", {})}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    status = None
    detail = ""
    try:
        with opener.open(request, timeout=2) as response:
            status = response.status
        healthy = status < http.client.INTERNAL_SERVER_ERROR
        detail = f"HTTP {status}"
    except urllib.error.HTTPError as exc:
        status = exc.code
        healthy = status < http.client.INTERNAL_SERVER_ERROR
        detail = f"HTTP {status}"
    except (OSError, urllib.error.URLError) as exc:
        healthy = False
        detail = str(exc.reason if isinstance(exc, urllib.error.URLError) else exc)
    return {
        "healthy": healthy,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "status_code": status,
        "detail": detail,
    }


def check_status(check: dict[str, Any]) -> dict[str, Any]:
    if check["type"] == "tcp":
        return tcp_check(check)
    if check["type"] == "http":
        return http_check(check)
    return {"healthy": False, "latency_ms": 0, "detail": "unsupported check"}


def cpu_percent() -> float:
    def sample() -> tuple[int, int]:
        fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()[1:]
        values = [int(value) for value in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return idle, sum(values)

    first_idle, first_total = sample()
    time.sleep(0.12)
    second_idle, second_total = sample()
    total_delta = second_total - first_total
    if total_delta <= 0:
        return 0.0
    return round(100 * (1 - (second_idle - first_idle) / total_delta), 1)


def host_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    memory: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    disk = shutil.disk_usage("/data")
    uptime = float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
    total_memory = memory.get("MemTotal", 0)
    available_memory = memory.get("MemAvailable", 0)
    return {
        **config["host"],
        "hostname": platform.node(),
        "cpu_percent": cpu_percent(),
        "load_average": [round(value, 2) for value in os.getloadavg()],
        "memory_total": total_memory,
        "memory_used": total_memory - available_memory,
        "memory_percent": round(100 * (total_memory - available_memory) / total_memory, 1)
        if total_memory
        else 0,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_percent": round(100 * disk.used / disk.total, 1) if disk.total else 0,
        "uptime_seconds": round(uptime),
        "platform": platform.platform(),
    }


def project_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(project)
    for component in output["components"]:
        try:
            component.update(component_status(component))
        except OpsFailure as exc:
            component.update(
                {"state": "unknown", "substate": "error", "healthy": False, "detail": str(exc)}
            )
    for check in output.get("checks", []):
        check.update(check_status(check))

    required_items = [
        component["healthy"]
        for component in output["components"]
        if component.get("required", True)
    ] + [check["healthy"] for check in output.get("checks", [])]
    all_items = [component["healthy"] for component in output["components"]] + [
        check["healthy"] for check in output.get("checks", [])
    ]
    if all_items and all(all_items):
        output["status"] = "healthy"
    elif any(required_items):
        output["status"] = "degraded"
    else:
        output["status"] = "offline"
    return output


def snapshot(config: dict[str, Any]) -> dict[str, Any]:
    projects = [project_snapshot(project) for project in config["projects"]]
    applications = [project for project in projects if project.get("kind") == "application"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": host_snapshot(config),
        "summary": {
            "healthy": sum(project["status"] == "healthy" for project in applications),
            "degraded": sum(project["status"] == "degraded" for project in applications),
            "offline": sum(project["status"] == "offline" for project in applications),
            "total": len(applications),
        },
        "projects": projects,
    }


def perform_action(
    config: dict[str, Any], project_id: str, component_id: str, action: str
) -> dict[str, Any]:
    _, component = find_component(config, project_id, component_id)
    if action not in ALLOWED_ACTIONS or action not in component.get("actions", []):
        raise OpsFailure("action is not allowed for this component")

    if component["type"] == "systemd":
        command = [SYSTEMCTL, action, component["service"]]
    elif component["type"] == "user_systemd":
        command = user_systemctl_prefix(component["user"]) + [action, component["service"]]
    elif component["type"] == "compose":
        command = [DOCKER, "compose", "-f", component["compose_file"]]
        if action == "start":
            command += ["up", "-d"]
        elif action == "restart":
            command += ["restart"]
        else:
            command += ["stop"]
    else:
        raise OpsFailure("component does not support actions")

    result = run(command, timeout=90)
    if result.returncode != 0:
        raise OpsFailure((result.stderr or result.stdout).strip()[-1000:] or "action failed")
    return {
        "ok": True,
        "message": (result.stdout or result.stderr).strip()[-1000:] or f"{action} completed",
    }


def read_logs(config: dict[str, Any], project_id: str, component_id: str, lines: int) -> str:
    _, component = find_component(config, project_id, component_id)
    safe_lines = max(20, min(lines, 1000))
    if component["type"] == "systemd":
        command = [
            JOURNALCTL,
            "--unit",
            component["service"],
            "--no-pager",
            "--output=short-iso",
            "--lines",
            str(safe_lines),
        ]
    elif component["type"] == "user_systemd":
        uid = pwd.getpwnam(component["user"]).pw_uid
        command = [
            JOURNALCTL,
            f"_UID={uid}",
            f"_SYSTEMD_USER_UNIT={component['service']}",
            "--no-pager",
            "--output=short-iso",
            "--lines",
            str(safe_lines),
        ]
    elif component["type"] == "compose":
        command = [
            DOCKER,
            "compose",
            "-f",
            component["compose_file"],
            "logs",
            "--no-color",
            "--tail",
            str(safe_lines),
        ]
    elif component["type"] == "cron":
        if not Path(component["log_path"]).exists():
            return f"日志文件尚未生成：{component['log_path']}\n"
        command = [TAIL, "-n", str(safe_lines), component["log_path"]]
    else:
        raise OpsFailure("logs are not supported for this component")
    result = run(command, timeout=20)
    if result.returncode != 0:
        raise OpsFailure((result.stderr or "cannot read logs").strip()[-1000:])
    output = result.stdout
    if len(output) > 500_000:
        output = output[-500_000:]
    return output


def _require_pattern(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise OpsFailure(f"invalid {label}")
    return value


def _json_output(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _protected_package(name: str) -> bool:
    base_name = name.split(":", 1)[0]
    return base_name in PROTECTED_PACKAGES or base_name.startswith(PROTECTED_PACKAGE_PREFIXES)


def software_inventory(query: str, limit: int) -> dict[str, Any]:
    normalized = query.strip().lower()
    safe_limit = max(20, min(limit, 500))
    result = run(
        [
            DPKG_QUERY,
            "-W",
            "-f=${binary:Package}\t${Version}\t${Architecture}\t${Installed-Size}\t${db:Status-Abbrev}\n",
        ],
        timeout=30,
    )
    installed: list[dict[str, Any]] = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) != 5 or not fields[4].startswith("ii"):
                continue
            name, version, architecture, size_kb, _ = fields
            if normalized and normalized not in name.lower():
                continue
            installed.append(
                {
                    "manager": "apt",
                    "name": name,
                    "version": version,
                    "architecture": architecture,
                    "size_bytes": int(size_kb or 0) * 1024,
                    "installed": True,
                    "description": "",
                    "protected": _protected_package(name),
                }
            )
            if len(installed) >= safe_limit:
                break

    available: list[dict[str, Any]] = []
    installed_names = {item["name"] for item in installed}
    if normalized and PACKAGE_PATTERN.fullmatch(normalized):
        search = run([APT_CACHE, "search", "--names-only", normalized], timeout=30)
        if search.returncode == 0:
            for line in search.stdout.splitlines():
                name, separator, description = line.partition(" - ")
                if not separator or not PACKAGE_PATTERN.fullmatch(name):
                    continue
                if name in installed_names:
                    continue
                available.append(
                    {
                        "manager": "apt",
                        "name": name,
                        "version": None,
                        "architecture": None,
                        "size_bytes": None,
                        "installed": False,
                        "description": description,
                        "protected": False,
                    }
                )
                if len(available) >= min(safe_limit, 100):
                    break

    snaps: list[dict[str, Any]] = []
    snap_binary = shutil.which("snap")
    if snap_binary:
        snap_result = run([snap_binary, "list"], timeout=30)
        if snap_result.returncode == 0:
            for line in snap_result.stdout.splitlines()[1:]:
                fields = line.split()
                if len(fields) < 4:
                    continue
                name, version, revision, tracking = fields[:4]
                if normalized and normalized not in name.lower():
                    continue
                snaps.append(
                    {
                        "manager": "snap",
                        "name": name,
                        "version": version,
                        "revision": revision,
                        "tracking": tracking,
                        "installed": True,
                        "size_bytes": None,
                        "description": "Snap package",
                        "protected": name in PROTECTED_SNAPS,
                    }
                )

    return {
        "query": query,
        "items": installed + snaps + available,
        "counts": {
            "installed": len(installed) + len(snaps),
            "available": len(available),
        },
        "managers": {"apt": True, "snap": bool(snap_binary)},
    }


def software_plan(manager: str, name: str, action: str) -> dict[str, Any]:
    if manager not in {"apt", "snap"}:
        raise OpsFailure("unsupported package manager")
    if action != "refresh":
        _require_pattern(name, PACKAGE_PATTERN, "package name")
    if action in {"remove", "purge"} and (
        _protected_package(name) or (manager == "snap" and name in PROTECTED_SNAPS)
    ):
        raise OpsFailure("protected system package cannot be removed")

    if manager == "apt":
        commands = {
            "install": [APT_GET, "--simulate", "install", name],
            "upgrade": [APT_GET, "--simulate", "install", "--only-upgrade", name],
            "remove": [APT_GET, "--simulate", "remove", name],
            "purge": [APT_GET, "--simulate", "purge", name],
            "refresh": [APT_GET, "--simulate", "upgrade"],
        }
        command = commands.get(action)
        if not command:
            raise OpsFailure("unsupported software action")
        result = run(command, timeout=60, extra_env={"DEBIAN_FRONTEND": "noninteractive"})
    else:
        if action not in {"install", "remove", "refresh"}:
            raise OpsFailure("unsupported Snap action")
        result = subprocess.CompletedProcess([], 0, f"snap {action} {name}".strip(), "")
    if result.returncode != 0:
        raise OpsFailure((result.stderr or result.stdout).strip()[-2000:] or "cannot build plan")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    for line in lines:
        fields = line.split()
        if (
            fields
            and fields[0] in {"Remv", "Purg"}
            and len(fields) > 1
            and _protected_package(fields[1])
        ):
            raise OpsFailure("operation would remove a protected system package")
    changes = [
        line
        for line in lines
        if line.startswith(("Inst ", "Remv ", "Purg ", "Conf ", "The following"))
    ]
    return {
        "manager": manager,
        "name": name,
        "action": action,
        "changes": changes[-80:],
        "summary": "\n".join(lines[-30:])[-6000:],
    }


def perform_software_action(manager: str, name: str, action: str) -> dict[str, Any]:
    software_plan(manager, name, action)
    if manager == "apt":
        commands = {
            "install": [APT_GET, "install", "-y", name],
            "upgrade": [APT_GET, "install", "-y", "--only-upgrade", name],
            "remove": [APT_GET, "remove", "-y", name],
            "purge": [APT_GET, "purge", "-y", name],
            "refresh": [APT_GET, "update"],
        }
        result = run(
            commands[action], timeout=900, extra_env={"DEBIAN_FRONTEND": "noninteractive"}
        )
    else:
        snap_binary = shutil.which("snap")
        if not snap_binary:
            raise OpsFailure("Snap is unavailable")
        command = [snap_binary, action]
        if name != "_":
            command.append(name)
        result = run(command, timeout=900)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[-3000:]
        raise OpsFailure(message or "software action failed")
    return {"ok": True, "message": (result.stdout or "operation completed").strip()[-3000:]}


def _systemd_units(base: list[str], scope: str) -> list[dict[str, Any]]:
    unit_types = "service,timer,socket,path"
    files = run(
        base
        + ["list-unit-files", f"--type={unit_types}", "--no-legend", "--no-pager"]
    )
    units = run(
        base
        + ["list-units", "--all", f"--type={unit_types}", "--no-legend", "--no-pager"]
    )
    active_map: dict[str, tuple[str, str]] = {}
    if units.returncode == 0:
        for line in units.stdout.splitlines():
            fields = line.lstrip("● ").split(None, 4)
            if len(fields) >= 4:
                active_map[fields[0]] = (fields[2], fields[3])
    output: list[dict[str, Any]] = []
    if files.returncode == 0:
        for line in files.stdout.splitlines():
            fields = line.split()
            if len(fields) < 2 or not UNIT_PATTERN.fullmatch(fields[0]):
                continue
            unit = fields[0]
            active, substate = active_map.get(unit, ("inactive", "dead"))
            output.append(
                {
                    "scope": scope,
                    "name": unit,
                    "enabled_state": fields[1],
                    "active_state": active,
                    "substate": substate,
                    "protected": unit in PROTECTED_UNITS,
                }
            )
    return output


def startup_inventory(query: str, limit: int) -> dict[str, Any]:
    normalized = query.strip().lower()
    items = _systemd_units([SYSTEMCTL], "system")
    with suppress(OpsFailure):
        items.extend(_systemd_units(user_systemctl_prefix("huxi"), "user"))

    ids = run([DOCKER, "ps", "-aq"], timeout=20)
    if ids.returncode == 0 and ids.stdout.strip():
        inspected = run([DOCKER, "inspect", *ids.stdout.split()], timeout=30)
        if inspected.returncode == 0:
            try:
                containers = json.loads(inspected.stdout)
            except json.JSONDecodeError:
                containers = []
            for container in containers:
                name = container.get("Name", "").lstrip("/")
                state = container.get("State", {})
                policy = container.get("HostConfig", {}).get("RestartPolicy", {}).get("Name", "no")
                items.append(
                    {
                        "scope": "docker",
                        "name": name,
                        "enabled_state": policy or "no",
                        "active_state": state.get("Status", "unknown"),
                        "substate": "healthy"
                        if state.get("Health", {}).get("Status") == "healthy"
                        else state.get("Status", "unknown"),
                        "protected": False,
                    }
                )

    if normalized:
        items = [item for item in items if normalized in item["name"].lower()]
    items.sort(key=lambda item: (item["scope"], item["name"]))
    safe_limit = max(20, min(limit, 1000))
    return {"items": items[:safe_limit], "total": len(items)}


def perform_startup_action(scope: str, name: str, action: str, value: str) -> dict[str, Any]:
    if scope in {"system", "user"}:
        _require_pattern(name, UNIT_PATTERN, "unit name")
        if action not in {"start", "stop", "restart", "enable", "disable"}:
            raise OpsFailure("unsupported startup action")
        if name in PROTECTED_UNITS and action in {"stop", "disable"}:
            raise OpsFailure("protected service cannot be stopped or disabled here")
        base = [SYSTEMCTL] if scope == "system" else user_systemctl_prefix("huxi")
        result = run(base + [action, name], timeout=90)
    elif scope == "docker":
        _require_pattern(name, CONTAINER_PATTERN, "container name")
        if action != "policy" or value not in {"no", "always", "unless-stopped", "on-failure"}:
            raise OpsFailure("invalid Docker restart policy")
        result = run([DOCKER, "update", "--restart", value, name], timeout=60)
    else:
        raise OpsFailure("unsupported startup scope")
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[-2000:]
        raise OpsFailure(message or "startup action failed")
    return {"ok": True, "message": (result.stdout or f"{action} completed").strip()[-2000:]}


def _memory_details() -> dict[str, int | float]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.strip().split()[0]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    return {
        "total": total,
        "available": available,
        "used": total - available,
        "percent": round(100 * (total - available) / total, 1) if total else 0,
        "cached": values.get("Cached", 0) + values.get("SReclaimable", 0),
        "buffers": values.get("Buffers", 0),
        "swap_total": swap_total,
        "swap_used": swap_total - swap_free,
        "swap_percent": round(100 * (swap_total - swap_free) / swap_total, 1)
        if swap_total
        else 0,
    }


def _filesystem_details() -> list[dict[str, Any]]:
    inodes: dict[str, dict[str, int | float]] = {}
    inode_result = run([DF, "-Pi"], timeout=20)
    for line in inode_result.stdout.splitlines()[1:]:
        fields = line.split(None, 5)
        if len(fields) == 6:
            inodes[fields[5]] = {
                "inodes": int(fields[1]),
                "inodes_used": int(fields[2]),
                "inodes_percent": float(fields[4].rstrip("%") or 0),
            }
    result = run([DF, "-B1", "-P", "-T"], timeout=20)
    output = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split(None, 6)
        if len(fields) != 7:
            continue
        source, fstype, size, used, available, percent, mountpoint = fields
        if fstype in {"tmpfs", "devtmpfs", "squashfs", "overlay"}:
            continue
        output.append(
            {
                "source": source,
                "fstype": fstype,
                "mountpoint": mountpoint,
                "size": int(size),
                "used": int(used),
                "available": int(available),
                "percent": float(percent.rstrip("%") or 0),
                **inodes.get(mountpoint, {}),
            }
        )
    return output


def _process_details() -> list[dict[str, Any]]:
    result = run(
        [PS, "-eo", "pid=,user=,comm=,%cpu=,%mem=,rss=,stat=", "--sort=-%cpu"],
        timeout=20,
    )
    output = []
    for line in result.stdout.splitlines()[:40]:
        fields = line.split(None, 6)
        if len(fields) != 7:
            continue
        try:
            output.append(
                {
                    "pid": int(fields[0]),
                    "user": fields[1],
                    "command": fields[2],
                    "cpu_percent": float(fields[3]),
                    "memory_percent": float(fields[4]),
                    "rss_bytes": int(fields[5]) * 1024,
                    "state": fields[6],
                }
            )
        except ValueError:
            continue
    return output


def _container_stats() -> list[dict[str, Any]]:
    result = run([DOCKER, "stats", "--no-stream", "--format", "{{json .}}"], timeout=30)
    output = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            output.append(
                {
                    "name": item.get("Name"),
                    "cpu": item.get("CPUPerc"),
                    "memory": item.get("MemUsage"),
                    "memory_percent": item.get("MemPerc"),
                    "network": item.get("NetIO"),
                    "block_io": item.get("BlockIO"),
                    "pids": item.get("PIDs"),
                }
            )
    return output


def _network_details() -> list[dict[str, Any]]:
    output = []
    for line in Path("/proc/net/dev").read_text(encoding="ascii").splitlines()[2:]:
        interface, separator, values = line.partition(":")
        if not separator:
            continue
        fields = values.split()
        if len(fields) >= 16:
            output.append(
                {
                    "interface": interface.strip(),
                    "received_bytes": int(fields[0]),
                    "received_packets": int(fields[1]),
                    "received_errors": int(fields[2]),
                    "sent_bytes": int(fields[8]),
                    "sent_packets": int(fields[9]),
                    "sent_errors": int(fields[10]),
                }
            )
    return output


def _temperature_details() -> list[dict[str, Any]]:
    output = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(path.read_text(encoding="ascii").strip()) / 1000
            label_path = path.parent / "type"
            label = (
                label_path.read_text(encoding="ascii").strip()
                if label_path.exists()
                else path.parent.name
            )
            if -20 <= value <= 150:
                output.append({"label": label, "celsius": round(value, 1)})
        except (OSError, ValueError):
            continue
    return output


def system_details() -> dict[str, Any]:
    cpu_model = "Unknown CPU"
    cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    for line in cpuinfo.splitlines():
        if line.startswith("model name"):
            cpu_model = line.partition(":")[2].strip()
            break
    lsblk = run(
        [LSBLK, "-J", "-b", "-o", "NAME,PATH,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL,ROTA,TRAN"],
        timeout=20,
    )
    try:
        block_devices = json.loads(lsblk.stdout).get("blockdevices", [])
    except json.JSONDecodeError:
        block_devices = []
    failed = run([SYSTEMCTL, "--failed", "--no-legend", "--no-pager"], timeout=20)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cpu": {
            "model": cpu_model,
            "cores": os.cpu_count() or 1,
            "percent": cpu_percent(),
            "load_average": [round(value, 2) for value in os.getloadavg()],
            "temperatures": _temperature_details(),
        },
        "memory": _memory_details(),
        "filesystems": _filesystem_details(),
        "block_devices": block_devices,
        "processes": _process_details(),
        "containers": _container_stats(),
        "network": _network_details(),
        "uptime_seconds": round(float(Path("/proc/uptime").read_text().split()[0])),
        "failed_units": len([line for line in failed.stdout.splitlines() if line.strip()]),
        "smart_available": bool(shutil.which("smartctl")),
    }


def _directory_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total


def maintenance_scan() -> dict[str, Any]:
    apt_cache = _directory_size(Path("/var/cache/apt/archives"))
    journal = run([JOURNALCTL, "--disk-usage", "--no-pager"], timeout=30)
    journal_text = (journal.stdout or journal.stderr).strip()
    tmp_size = 0
    tmp_count = 0
    cutoff = time.time() - 7 * 86400
    for root, directories, files in os.walk("/tmp", topdown=True, followlinks=False):
        directories[:] = [name for name in directories if not Path(root, name).is_symlink()]
        for name in files:
            path = Path(root, name)
            try:
                stat = path.lstat()
                if stat.st_mtime < cutoff and not path.is_symlink():
                    tmp_count += 1
                    tmp_size += stat.st_size
            except OSError:
                continue
    docker_df = run([DOCKER, "system", "df", "--format", "{{json .}}"], timeout=30)
    docker_rows = []
    for line in docker_df.stdout.splitlines():
        try:
            docker_rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    autoremove = run(
        [APT_GET, "--simulate", "autoremove"],
        timeout=60,
        extra_env={"DEBIAN_FRONTEND": "noninteractive"},
    )
    removable = sum(line.startswith("Remv ") for line in autoremove.stdout.splitlines())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": [
            {
                "id": "apt-cache",
                "label": "APT 下载缓存",
                "risk": "safe",
                "size_bytes": apt_cache,
                "detail": "/var/cache/apt/archives",
            },
            {
                "id": "journal-14d",
                "label": "14 天前的系统日志",
                "risk": "safe",
                "size_bytes": None,
                "detail": journal_text,
            },
            {
                "id": "tmp-7d",
                "label": "7 天未修改的临时文件",
                "risk": "safe",
                "size_bytes": tmp_size,
                "detail": f"{tmp_count} files under /tmp",
            },
            {
                "id": "docker-build-cache",
                "label": "Docker 构建缓存",
                "risk": "medium",
                "size_bytes": None,
                "detail": next(
                    (
                        str(row.get("Reclaimable", "0B"))
                        for row in docker_rows
                        if row.get("Type") == "Build Cache"
                    ),
                    "0B",
                ),
            },
            {
                "id": "docker-dangling-images",
                "label": "Docker 悬空镜像",
                "risk": "medium",
                "size_bytes": None,
                "detail": "Only untagged images not used by containers",
            },
            {
                "id": "apt-autoremove",
                "label": "不再需要的软件依赖",
                "risk": "medium",
                "size_bytes": None,
                "detail": f"{removable} packages",
            },
            {
                "id": "docker-volumes",
                "label": "未使用 Docker 卷",
                "risk": "high",
                "size_bytes": None,
                "detail": "仅展示；面板不会自动删除数据卷",
                "actionable": False,
            },
        ],
        "docker": docker_rows,
    }


def perform_maintenance_action(action: str) -> dict[str, Any]:
    commands = {
        "apt-cache": [APT_GET, "clean"],
        "journal-14d": [JOURNALCTL, "--vacuum-time=14d"],
        "tmp-7d": ["/usr/bin/find", "/tmp", "-xdev", "-mindepth", "1", "-mtime", "+7", "-delete"],
        "docker-build-cache": [DOCKER, "builder", "prune", "-f"],
        "docker-dangling-images": [DOCKER, "image", "prune", "-f"],
        "apt-autoremove": [APT_GET, "autoremove", "-y"],
    }
    command = commands.get(action)
    if not command:
        raise OpsFailure("cleanup action is not allowed")
    result = run(command, timeout=900, extra_env={"DEBIAN_FRONTEND": "noninteractive"})
    if result.returncode != 0:
        raise OpsFailure((result.stderr or result.stdout).strip()[-3000:] or "cleanup failed")
    return {"ok": True, "message": (result.stdout or "cleanup completed").strip()[-3000:]}


def optimization_scan() -> dict[str, Any]:
    fstrim_enabled = run([SYSTEMCTL, "is-enabled", "fstrim.timer"], timeout=10)
    fstrim_active = run([SYSTEMCTL, "is-active", "fstrim.timer"], timeout=10)
    swappiness = Path("/proc/sys/vm/swappiness").read_text().strip()
    journal_dropin = Path("/etc/systemd/journald.conf.d/90-ai-tool-limits.conf")
    failed = run([SYSTEMCTL, "--failed", "--no-legend", "--no-pager"], timeout=20)
    updates = run([APT_GET, "--simulate", "upgrade"], timeout=60)
    update_count = sum(line.startswith("Inst ") for line in updates.stdout.splitlines())
    recommendations = [
        {
            "id": "enable-fstrim",
            "label": "启用定期 SSD/TRIM",
            "status": "applied" if fstrim_enabled.returncode == 0 else "recommended",
            "detail": (
                f"enabled={fstrim_enabled.stdout.strip()} "
                f"active={fstrim_active.stdout.strip()}"
            ),
            "reversible": True,
        },
        {
            "id": "limit-journal",
            "label": "限制 systemd journal 占用",
            "status": "applied" if journal_dropin.exists() else "recommended",
            "detail": "SystemMaxUse=500M, RuntimeMaxUse=200M",
            "reversible": True,
        },
        {
            "id": "package-updates",
            "label": "安装系统更新",
            "status": "attention" if update_count else "ok",
            "detail": f"{update_count} packages can be upgraded",
            "reversible": False,
            "actionable": False,
        },
        {
            "id": "failed-services",
            "label": "处理失败的 systemd 服务",
            "status": "attention" if failed.stdout.strip() else "ok",
            "detail": (
                f"{len([line for line in failed.stdout.splitlines() if line.strip()])} "
                "failed units"
            ),
            "reversible": False,
            "actionable": False,
        },
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recommendations": recommendations,
        "facts": {
            "swappiness": int(swappiness),
            "reboot_required": Path("/var/run/reboot-required").exists(),
            "updates": update_count,
        },
    }


def perform_optimization_action(action: str) -> dict[str, Any]:
    if action == "enable-fstrim":
        result = run([SYSTEMCTL, "enable", "--now", "fstrim.timer"], timeout=60)
    elif action == "disable-fstrim":
        result = run([SYSTEMCTL, "disable", "--now", "fstrim.timer"], timeout=60)
    elif action == "limit-journal":
        directory = Path("/etc/systemd/journald.conf.d")
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "90-ai-tool-limits.conf"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            "[Journal]\nSystemMaxUse=500M\nRuntimeMaxUse=200M\nMaxRetentionSec=30day\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o644)
        temporary.replace(target)
        result = run([SYSTEMCTL, "restart", "systemd-journald.service"], timeout=60)
    elif action == "rollback-journal":
        Path("/etc/systemd/journald.conf.d/90-ai-tool-limits.conf").unlink(missing_ok=True)
        result = run([SYSTEMCTL, "restart", "systemd-journald.service"], timeout=60)
    else:
        raise OpsFailure("optimization action is not allowed")
    if result.returncode != 0:
        raise OpsFailure((result.stderr or result.stdout).strip()[-2000:] or "optimization failed")
    return {"ok": True, "message": (result.stdout or f"{action} completed").strip()[-2000:]}


def _decode_payload(encoded: str) -> dict[str, Any]:
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpsFailure("invalid encoded payload") from exc
    if not isinstance(value, dict):
        raise OpsFailure("payload must be an object")
    return value


def _load_web_state() -> list[dict[str, Any]]:
    if not WEB_STATE_PATH.exists():
        return []
    try:
        value = json.loads(WEB_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpsFailure("managed web service state is invalid") from exc
    if not isinstance(value, list):
        raise OpsFailure("managed web service state is invalid")
    if any(not isinstance(item, dict) for item in value):
        raise OpsFailure("managed web service state is invalid")
    try:
        return [_validate_web_service(item) for item in value]
    except OpsFailure as exc:
        raise OpsFailure("managed web service state is invalid") from exc


def _save_web_state(items: list[dict[str, Any]]) -> None:
    WEB_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = WEB_STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(WEB_STATE_PATH)


def _ensure_web_layout() -> None:
    WEB_AVAILABLE_DIR.mkdir(parents=True, exist_ok=True)
    WEB_ENABLED_DIR.mkdir(parents=True, exist_ok=True)
    WEB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not WEB_INCLUDE_PATH.exists():
        WEB_INCLUDE_PATH.write_text(
            "# Managed by AI Tool\ninclude /etc/nginx/ai-tool-sites-enabled/*.conf;\n",
            encoding="utf-8",
        )
        os.chmod(WEB_INCLUDE_PATH, 0o644)


def _validate_web_service(value: dict[str, Any]) -> dict[str, Any]:
    service_id = _require_pattern(str(value.get("id", "")), WEB_ID_PATTERN, "web service id")
    domain = _require_pattern(str(value.get("domain", "")), DOMAIN_PATTERN, "domain")
    name = str(value.get("name", "")).strip()
    if not name or len(name) > 100:
        raise OpsFailure("invalid web service name")
    upstream_host = str(value.get("upstream_host", ""))
    if upstream_host not in {"127.0.0.1", "localhost"}:
        raise OpsFailure("upstream host must be local")
    try:
        upstream_port = int(value.get("upstream_port"))
    except (TypeError, ValueError) as exc:
        raise OpsFailure("invalid upstream port") from exc
    if not 1 <= upstream_port <= 65535:
        raise OpsFailure("invalid upstream port")
    return {
        "id": service_id,
        "name": name,
        "domain": domain,
        "upstream_host": upstream_host,
        "upstream_port": upstream_port,
        "websocket": bool(value.get("websocket", True)),
        "enabled": bool(value.get("enabled", True)),
    }


def _render_nginx_service(service: dict[str, Any]) -> str:
    connection_header = ""
    if service["websocket"]:
        connection_header = (
            "        proxy_set_header Upgrade $http_upgrade;\n"
            '        proxy_set_header Connection "upgrade";\n'
        )
    return (
        "# Managed by AI Tool. Manual changes will be replaced.\n"
        "server {\n"
        "    listen 80;\n"
        f"    server_name {service['domain']};\n"
        f"    access_log /var/log/nginx/ai-tool-{service['id']}.access.log;\n"
        f"    error_log /var/log/nginx/ai-tool-{service['id']}.error.log;\n"
        "    location / {\n"
        f"        proxy_pass http://{service['upstream_host']}:{service['upstream_port']};\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        f"{connection_header}"
        "        proxy_read_timeout 300s;\n"
        "        client_max_body_size 100m;\n"
        "    }\n"
        "}\n"
    )


def _nginx_apply() -> None:
    test = run([NGINX, "-t"], timeout=30)
    if test.returncode != 0:
        raise OpsFailure((test.stderr or test.stdout).strip()[-3000:] or "nginx validation failed")
    reload_result = run([SYSTEMCTL, "reload", "nginx.service"], timeout=30)
    if reload_result.returncode != 0:
        message = (reload_result.stderr or reload_result.stdout).strip()[-2000:]
        raise OpsFailure(message or "nginx reload failed")


def _web_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (normalized or "web-service")[:63].rstrip("-")


def _url_port(value: str) -> int | None:
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        return parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def _project_web_ports(config: dict[str, Any]) -> dict[int, list[dict[str, str]]]:
    by_port: dict[int, list[dict[str, str]]] = {}
    for project in config.get("projects", []):
        candidates = []
        if isinstance(project.get("url"), str):
            candidates.append(project["url"])
        candidates.extend(
            check["url"]
            for check in project.get("checks", [])
            if check.get("type") == "http" and isinstance(check.get("url"), str)
        )
        for url in candidates:
            port = _url_port(url)
            if port is None:
                continue
            item = {
                "id": str(project.get("id", "web-service")),
                "name": str(project.get("name", "Web service")),
            }
            entries = by_port.setdefault(port, [])
            if not any(existing["id"] == item["id"] for existing in entries):
                entries.append(item)
    return by_port


def _docker_published_ports() -> dict[int, list[str]]:
    listed = run([DOCKER, "ps", "--format", "{{.ID}}"], timeout=30)
    container_ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    if listed.returncode != 0:
        raise OpsFailure("Docker container inventory is unavailable")
    if not container_ids:
        return {}
    inspected = run([DOCKER, "inspect", *container_ids], timeout=40)
    if inspected.returncode != 0:
        raise OpsFailure("Docker port inventory is unavailable")
    try:
        containers = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise OpsFailure("Docker port inventory is invalid") from exc
    if not isinstance(containers, list):
        raise OpsFailure("Docker port inventory is invalid")
    published: dict[int, set[str]] = {}
    for container in containers:
        if not isinstance(container, dict):
            continue
        name = str(container.get("Name", "")).lstrip("/")
        ports = container.get("NetworkSettings", {}).get("Ports", {}) or {}
        if not isinstance(ports, dict):
            continue
        for container_port, bindings in ports.items():
            if not container_port.endswith("/tcp") or not isinstance(bindings, list):
                continue
            for binding in bindings:
                try:
                    host_port = int(binding.get("HostPort", ""))
                except (TypeError, ValueError):
                    continue
                published.setdefault(host_port, set()).add(name)
    return {port: sorted(containers) for port, containers in published.items()}


def _listener_endpoint(value: str) -> tuple[str, int] | None:
    if value.startswith("[") and "]:" in value:
        host, port_value = value[1:].rsplit("]:", 1)
    else:
        host, separator, port_value = value.rpartition(":")
        if not separator:
            return None
    try:
        return host.split("%", 1)[0], int(port_value)
    except ValueError:
        return None


def _service_for_pid(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    matches = re.findall(r"(?:^|/)([^/]+\.service)(?:/|$)", cgroup, re.MULTILINE)
    return matches[-1] if matches else None


def _tcp_listeners() -> dict[int, dict[str, Any]]:
    result = run([SS, "-lntpH"], timeout=30)
    if result.returncode != 0:
        raise OpsFailure("TCP listener inventory is unavailable")
    listeners: dict[int, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        endpoint = _listener_endpoint(fields[3])
        if endpoint is None:
            continue
        host, port = endpoint
        process_match = re.search(r'users:\(\("([^"]+)"', line)
        pid_match = re.search(r"\bpid=(\d+)", line)
        pid = int(pid_match.group(1)) if pid_match else None
        candidate = {
            "bind": host,
            "port": port,
            "process": process_match.group(1) if process_match else "unknown",
            "pid": pid,
            "service": _service_for_pid(pid),
        }
        current = listeners.get(port)
        priority = 3 if host == "0.0.0.0" else (2 if ":" not in host else 1)
        current_priority = 0
        if current:
            current_host = current["bind"]
            current_priority = (
                3 if current_host == "0.0.0.0" else (2 if ":" not in current_host else 1)
            )
        if not current or priority > current_priority:
            listeners[port] = candidate
    return listeners


def _http_probe(
    host: str,
    port: int,
    host_header: str | None = None,
    protocol: str = "http",
) -> dict[str, Any]:
    url_host = f"[{host}]" if ":" in host else host
    request = urllib.request.Request(
        f"{protocol}://{url_host}:{port}/",
        headers={
            "User-Agent": "ai-tool-discovery/1.0",
            **({"Host": host_header} if host_header else {}),
        },
    )
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    if protocol == "https":
        tls_context = ssl.create_default_context()
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=tls_context))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=1) as response:
            status_code = response.status
    except urllib.error.HTTPError as exc:
        status_code = exc.code
    except (OSError, urllib.error.URLError):
        return {"detected": False, "healthy": False, "status_code": None}
    return {
        "detected": True,
        "healthy": status_code < http.client.INTERNAL_SERVER_ERROR,
        "status_code": status_code,
    }


def _nginx_server_blocks(output: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    source = "unknown"
    block_lines: list[str] = []
    block_source = source
    depth = 0
    for line in output.splitlines():
        source_match = re.match(r"^# configuration file (.+):$", line)
        if source_match and depth == 0:
            source = source_match.group(1)
            continue
        if depth == 0 and re.match(r"^\s*server\s*\{", line):
            block_source = source
            block_lines = [line]
            depth = line.count("{") - line.count("}")
            if depth == 0:
                blocks.append({"source": block_source, "content": line})
                block_lines = []
            continue
        if depth > 0:
            block_lines.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0:
                blocks.append({"source": block_source, "content": "\n".join(block_lines)})
                block_lines = []
    return blocks


def _nginx_listen_port(content: str) -> tuple[int, str]:
    for match in re.finditer(r"^\s*listen\s+([^;]+);", content, re.MULTILINE):
        directive = match.group(1)
        endpoint = directive.split()[0]
        if endpoint.isdigit():
            return int(endpoint), "https" if "ssl" in directive.split() else "http"
        port_match = re.search(r":(\d+)$", endpoint)
        if port_match:
            return int(port_match.group(1)), "https" if "ssl" in directive.split() else "http"
    return 80, "http"


def _nginx_upstream(content: str) -> tuple[str | None, int | None]:
    match = re.search(r"^\s*proxy_pass\s+(https?://[^;]+);", content, re.MULTILINE)
    if not match:
        return None, None
    try:
        parsed = urllib.parse.urlsplit(match.group(1))
        return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None, None


def _discover_nginx(
    output: str,
    config: dict[str, Any],
    managed_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    host_address = str(config.get("host", {}).get("address", "127.0.0.1"))
    project_ports = _project_web_ports(config)
    managed_domains = {item["domain"] for item in managed_items}
    discovered: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for block in _nginx_server_blocks(output):
        content = block["content"]
        names = []
        for match in re.finditer(r"^\s*server_name\s+([^;]+);", content, re.MULTILINE):
            names.extend(match.group(1).split())
        if not names:
            names = ["_"]
        port, protocol = _nginx_listen_port(content)
        upstream_host, upstream_port = _nginx_upstream(content)
        local_upstream = upstream_host in {"127.0.0.1", "localhost", "::1"}
        probe_host = upstream_host if local_upstream else "127.0.0.1"
        probe_port = upstream_port if local_upstream and upstream_port else port
        probe_protocol = "http" if local_upstream else protocol
        known = project_ports.get(upstream_port or port, [])
        known_name = known[0]["name"] if len(known) == 1 else None
        for domain in names:
            key = (domain, port, block["source"])
            if key in seen:
                continue
            seen.add(key)
            host_header = None if domain == "_" else domain
            probe = _http_probe(probe_host, probe_port, host_header, probe_protocol)
            managed = domain in managed_domains
            display_domain = None if domain == "_" else domain
            access_host = display_domain or host_address
            default_port = 443 if protocol == "https" else 80
            port_suffix = "" if port == default_port else f":{port}"
            discovered.append(
                {
                    "id": _web_id(f"nginx-{display_domain or 'default'}-{port}"),
                    "name": known_name or (display_domain or "Nginx 默认站点"),
                    "url": f"{protocol}://{access_host}{port_suffix}",
                    "domain": display_domain,
                    "port": port,
                    "protocol": protocol,
                    "source": "nginx",
                    "source_detail": block["source"],
                    "exposure": "lan",
                    "healthy": probe["healthy"],
                    "status_code": probe["status_code"],
                    "managed": managed,
                    "suggested_service": None,
                    "upstream_host": upstream_host,
                    "upstream_port": upstream_port,
                }
            )
    return discovered


def _discover_direct_services(
    config: dict[str, Any],
    listeners: dict[int, dict[str, Any]],
    docker_ports: dict[int, list[str]],
    managed_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    host_address = str(config.get("host", {}).get("address", "127.0.0.1"))
    project_ports = _project_web_ports(config)
    managed_ports = {item["upstream_port"] for item in managed_items}
    managed_ids = {item["id"] for item in managed_items}
    discovered = []
    for port, listener in sorted(listeners.items()):
        if (
            port in NON_WEB_PORTS
            or listener["process"] == "nginx"
            or listener["process"] in INTERNAL_WEB_PROCESSES
        ):
            continue
        bind = listener["bind"]
        loopback = bind == "localhost" or bind.startswith("127.") or bind in {"::1", "[::1]"}
        probe_host = "127.0.0.1" if bind in {"0.0.0.0", "*", "::"} else bind
        probe = _http_probe(probe_host, port)
        known = project_ports.get(port, [])
        docker = docker_ports.get(port)
        if not probe["detected"] and not known:
            continue
        service = listener.get("service")
        if len(known) == 1:
            name = known[0]["name"]
            base_id = known[0]["id"]
        elif docker:
            name = docker[0]
            base_id = name
        elif service:
            name = SERVICE_DISPLAY_NAMES.get(service, service.removesuffix(".service"))
            base_id = name
        else:
            name = f"{listener['process']} :{port}"
            base_id = f"{listener['process']}-{port}"
        if docker:
            source = "docker"
            source_detail = ", ".join(docker)
        elif service:
            source = "systemd"
            source_detail = service
        elif known:
            source = "project"
            source_detail = known[0]["id"]
        else:
            source = "process"
            source_detail = f"{listener['process']} (PID {listener['pid'] or '-'})"
        public_host = "127.0.0.1" if loopback else host_address
        url_host = f"[{public_host}]" if ":" in public_host else public_host
        managed = port in managed_ports
        can_proxy = bind in {"0.0.0.0", "*", "::", "localhost", "127.0.0.1", "::1"}
        suggested_id = _web_id(base_id)
        if suggested_id in managed_ids:
            suggested_id = _web_id(f"{suggested_id}-{port}")
        suggestion = None
        if can_proxy and not managed:
            suggestion = {
                "id": suggested_id,
                "name": name,
                "domain": "",
                "upstream_host": "127.0.0.1",
                "upstream_port": port,
                "websocket": True,
                "enabled": True,
            }
        discovered.append(
            {
                "id": _web_id(f"direct-{base_id}-{port}"),
                "name": name,
                "url": f"http://{url_host}:{port}",
                "domain": None,
                "port": port,
                "protocol": "http",
                "source": source,
                "source_detail": source_detail,
                "exposure": "loopback" if loopback else "lan",
                "healthy": probe["healthy"],
                "status_code": probe["status_code"],
                "managed": managed,
                "suggested_service": suggestion,
                "upstream_host": "127.0.0.1" if can_proxy else None,
                "upstream_port": port,
            }
        )
    return discovered


def web_inventory(config: dict[str, Any]) -> dict[str, Any]:
    items = _load_web_state()
    warnings = []
    nginx_output = ""
    try:
        nginx = run([NGINX, "-T"], timeout=30)
        nginx_output = nginx.stdout + nginx.stderr
    except OpsFailure:
        nginx = None
    if nginx is None or nginx.returncode != 0:
        warnings.append("Nginx 配置读取失败")
    try:
        listeners = _tcp_listeners()
    except OpsFailure:
        listeners = {}
        warnings.append("监听端口读取失败")
    try:
        docker_ports = _docker_published_ports()
    except OpsFailure:
        docker_ports = {}
        warnings.append("Docker 端口读取失败")
    for item in items:
        try:
            endpoint = (item["upstream_host"], item["upstream_port"])
            with socket.create_connection(endpoint, timeout=1):
                item["upstream_healthy"] = True
        except OSError:
            item["upstream_healthy"] = False
    discovered = _discover_nginx(nginx_output, config, items)
    discovered.extend(_discover_direct_services(config, listeners, docker_ports, items))
    discovered.sort(
        key=lambda item: (item["source"] != "nginx", item["name"].lower(), item["port"])
    )
    return {
        "items": items,
        "discovered": discovered,
        "nginx_active": run([SYSTEMCTL, "is-active", "nginx.service"], timeout=10).returncode == 0,
        "warnings": warnings,
    }


def upsert_web_service(encoded: str) -> dict[str, Any]:
    service = _validate_web_service(_decode_payload(encoded))
    _ensure_web_layout()
    available = WEB_AVAILABLE_DIR / f"{service['id']}.conf"
    enabled = WEB_ENABLED_DIR / f"{service['id']}.conf"
    old_content = available.read_text(encoding="utf-8") if available.exists() else None
    old_enabled = enabled.exists() or enabled.is_symlink()
    temporary = available.with_suffix(".tmp")
    temporary.write_text(_render_nginx_service(service), encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(available)
    if service["enabled"]:
        enabled.unlink(missing_ok=True)
        enabled.symlink_to(available)
    else:
        enabled.unlink(missing_ok=True)
    try:
        _nginx_apply()
    except OpsFailure:
        enabled.unlink(missing_ok=True)
        if old_content is None:
            available.unlink(missing_ok=True)
        else:
            available.write_text(old_content, encoding="utf-8")
        if old_enabled and available.exists():
            enabled.symlink_to(available)
        raise
    items = [item for item in _load_web_state() if item.get("id") != service["id"]]
    items.append(service)
    items.sort(key=lambda item: item["id"])
    _save_web_state(items)
    return {"ok": True, "message": f"Web service {service['id']} saved"}


def perform_web_action(service_id: str, action: str) -> dict[str, Any]:
    _require_pattern(service_id, WEB_ID_PATTERN, "web service id")
    items = _load_web_state()
    service = next((item for item in items if item.get("id") == service_id), None)
    if not service:
        raise OpsFailure("managed web service does not exist")
    available = WEB_AVAILABLE_DIR / f"{service_id}.conf"
    enabled = WEB_ENABLED_DIR / f"{service_id}.conf"
    if action in {"enable", "disable"}:
        old_enabled = enabled.exists() or enabled.is_symlink()
        if action == "enable":
            if not available.exists():
                raise OpsFailure("managed Nginx configuration is missing")
            enabled.unlink(missing_ok=True)
            enabled.symlink_to(available)
            service["enabled"] = True
        else:
            enabled.unlink(missing_ok=True)
            service["enabled"] = False
        try:
            _nginx_apply()
        except OpsFailure:
            enabled.unlink(missing_ok=True)
            if old_enabled and available.exists():
                enabled.symlink_to(available)
            raise
        _save_web_state(items)
    elif action == "delete":
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup = WEB_BACKUP_DIR / f"{service_id}-{timestamp}.conf"
        old_enabled = enabled.exists() or enabled.is_symlink()
        if available.exists():
            WEB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(available, backup)
        enabled.unlink(missing_ok=True)
        available.unlink(missing_ok=True)
        try:
            _nginx_apply()
        except OpsFailure:
            if backup.exists():
                shutil.copy2(backup, available)
            if old_enabled and available.exists():
                enabled.symlink_to(available)
            raise
        _save_web_state([item for item in items if item.get("id") != service_id])
    elif action == "reload":
        _nginx_apply()
    else:
        raise OpsFailure("web action is not allowed")
    return {"ok": True, "message": f"Web service {service_id}: {action} completed"}


def read_web_logs(service_id: str, stream: str, lines: int) -> str:
    _require_pattern(service_id, WEB_ID_PATTERN, "web service id")
    if stream not in {"access", "error"}:
        raise OpsFailure("invalid web log stream")
    if not any(item.get("id") == service_id for item in _load_web_state()):
        raise OpsFailure("managed web service does not exist")
    safe_lines = max(20, min(lines, 1000))
    log_path = Path(f"/var/log/nginx/ai-tool-{service_id}.{stream}.log")
    if not log_path.exists():
        return f"Log file has not been created: {log_path}\n"
    result = run([TAIL, "-n", str(safe_lines), str(log_path)], timeout=20)
    if result.returncode != 0:
        raise OpsFailure((result.stderr or "cannot read web logs").strip()[-1000:])
    return result.stdout[-500_000:]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("snapshot")
    subparsers.add_parser("terminal-cleanup")

    action_parser = subparsers.add_parser("action")
    action_parser.add_argument("project_id")
    action_parser.add_argument("component_id")
    action_parser.add_argument("action", choices=sorted(ALLOWED_ACTIONS))

    logs_parser = subparsers.add_parser("logs")
    logs_parser.add_argument("project_id")
    logs_parser.add_argument("component_id")
    logs_parser.add_argument("lines", type=int)

    software_parser = subparsers.add_parser("software")
    software_parser.add_argument("query")
    software_parser.add_argument("limit", type=int)

    software_plan_parser = subparsers.add_parser("software-plan")
    software_plan_parser.add_argument("manager", choices=["apt", "snap"])
    software_plan_parser.add_argument("name")
    software_plan_parser.add_argument("action")

    software_action_parser = subparsers.add_parser("software-action")
    software_action_parser.add_argument("manager", choices=["apt", "snap"])
    software_action_parser.add_argument("name")
    software_action_parser.add_argument("action")

    startup_parser = subparsers.add_parser("startup")
    startup_parser.add_argument("query")
    startup_parser.add_argument("limit", type=int)

    startup_action_parser = subparsers.add_parser("startup-action")
    startup_action_parser.add_argument("scope", choices=["system", "user", "docker"])
    startup_action_parser.add_argument("name")
    startup_action_parser.add_argument("action")
    startup_action_parser.add_argument("value", nargs="?", default="_")

    subparsers.add_parser("system-details")
    subparsers.add_parser("maintenance-scan")

    maintenance_action_parser = subparsers.add_parser("maintenance-action")
    maintenance_action_parser.add_argument("action")

    subparsers.add_parser("optimization-scan")

    optimization_action_parser = subparsers.add_parser("optimization-action")
    optimization_action_parser.add_argument("action")

    subparsers.add_parser("web-inventory")

    web_upsert_parser = subparsers.add_parser("web-upsert")
    web_upsert_parser.add_argument("payload")

    web_action_parser = subparsers.add_parser("web-action")
    web_action_parser.add_argument("service_id")
    web_action_parser.add_argument("action")

    web_logs_parser = subparsers.add_parser("web-logs")
    web_logs_parser.add_argument("service_id")
    web_logs_parser.add_argument("stream", choices=["access", "error"])
    web_logs_parser.add_argument("lines", type=int)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        if args.command == "terminal-cleanup":
            print(json.dumps(terminal_cleanup(), ensure_ascii=False))
            return 0
        config = load_config()
        if args.command == "snapshot":
            print(json.dumps(snapshot(config), ensure_ascii=False))
        elif args.command == "action":
            print(
                json.dumps(
                    perform_action(config, args.project_id, args.component_id, args.action),
                    ensure_ascii=False,
                )
            )
        elif args.command == "logs":
            sys.stdout.write(read_logs(config, args.project_id, args.component_id, args.lines))
        elif args.command == "software":
            print(_json_output(software_inventory(args.query, args.limit)))
        elif args.command == "software-plan":
            print(_json_output(software_plan(args.manager, args.name, args.action)))
        elif args.command == "software-action":
            print(_json_output(perform_software_action(args.manager, args.name, args.action)))
        elif args.command == "startup":
            print(_json_output(startup_inventory(args.query, args.limit)))
        elif args.command == "startup-action":
            print(
                _json_output(
                    perform_startup_action(args.scope, args.name, args.action, args.value)
                )
            )
        elif args.command == "system-details":
            print(_json_output(system_details()))
        elif args.command == "maintenance-scan":
            print(_json_output(maintenance_scan()))
        elif args.command == "maintenance-action":
            print(_json_output(perform_maintenance_action(args.action)))
        elif args.command == "optimization-scan":
            print(_json_output(optimization_scan()))
        elif args.command == "optimization-action":
            print(_json_output(perform_optimization_action(args.action)))
        elif args.command == "web-inventory":
            print(_json_output(web_inventory(config)))
        elif args.command == "web-upsert":
            print(_json_output(upsert_web_service(args.payload)))
        elif args.command == "web-action":
            print(_json_output(perform_web_action(args.service_id, args.action)))
        elif args.command == "web-logs":
            sys.stdout.write(read_web_logs(args.service_id, args.stream, args.lines))
        return 0
    except OpsFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
