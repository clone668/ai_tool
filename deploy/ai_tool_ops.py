#!/usr/bin/env python3
"""Root-owned allowlisted operations helper for AI Tool.

The web process can invoke only project/component/action combinations declared in
/etc/ai-tool/projects.json. No shell is used and no path is accepted from the caller.
"""

from __future__ import annotations

import argparse
import copy
import http.client
import json
import os
import platform
import pwd
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
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


class OpsFailure(RuntimeError):
    pass


def run(command: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("snapshot")

    action_parser = subparsers.add_parser("action")
    action_parser.add_argument("project_id")
    action_parser.add_argument("component_id")
    action_parser.add_argument("action", choices=sorted(ALLOWED_ACTIONS))

    logs_parser = subparsers.add_parser("logs")
    logs_parser.add_argument("project_id")
    logs_parser.add_argument("component_id")
    logs_parser.add_argument("lines", type=int)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
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
        return 0
    except OpsFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
