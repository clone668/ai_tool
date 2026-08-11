from __future__ import annotations

import copy
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .config import Settings, find_project_component, load_config


class OpsError(RuntimeError):
    pass


class OpsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.config = load_config(settings.config_path)
        self._cached_snapshot: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def _command(self, *arguments: str, timeout: int) -> str:
        helper = str(self.settings.ops_helper)
        command = [helper, *arguments]
        if os.name != "nt" and os.getenv("AI_TOOL_OPS_DIRECT") != "1":
            command = ["/usr/bin/sudo", "-n", *command]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OpsError("运维辅助程序不可用") from exc
        if result.returncode != 0:
            raise OpsError((result.stderr or result.stdout).strip()[-1000:] or "运维操作失败")
        return result.stdout

    def _demo_snapshot(self) -> dict[str, Any]:
        config = copy.deepcopy(self.config)
        projects = []
        for index, project in enumerate(config["projects"]):
            project["status"] = "degraded" if index == 3 else "healthy"
            for component_index, component in enumerate(project["components"]):
                component.update(
                    {
                        "state": "active" if component["type"] != "compose" else "running",
                        "substate": "running",
                        "healthy": not (index == 3 and component_index == 1),
                        "pid": 1400 + index * 10 + component_index,
                        "memory_bytes": 58_720_256 + index * 4_194_304,
                        "since": "2026-08-09 10:05:44 CST",
                        "detail": component.get("compose_file", "loaded"),
                    }
                )
                if component["type"] == "compose":
                    component["children"] = [
                        {
                            "name": name,
                            "state": "running",
                            "health": "healthy" if "sub2api" in name else None,
                            "healthy": True,
                            "restart_count": 0,
                        }
                        for name in component["containers"]
                    ]
            for check in project.get("checks", []):
                check.update({"healthy": True, "latency_ms": 12 + index, "detail": "HTTP 200"})
            projects.append(project)
        applications = [item for item in projects if item.get("kind") == "application"]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "host": {
                **config["host"],
                "hostname": "huxi-H81M",
                "cpu_percent": 18.4,
                "load_average": [0.42, 0.36, 0.31],
                "memory_total": 16 * 1024**3,
                "memory_used": 6.3 * 1024**3,
                "memory_percent": 39.4,
                "disk_total": 1.8 * 1024**4,
                "disk_used": 17 * 1024**3,
                "disk_percent": 1.0,
                "uptime_seconds": 192_420,
                "platform": "Linux 7.0.0-28-generic",
            },
            "summary": {
                "healthy": sum(item["status"] == "healthy" for item in applications),
                "degraded": sum(item["status"] == "degraded" for item in applications),
                "offline": sum(item["status"] == "offline" for item in applications),
                "total": len(applications),
            },
            "projects": projects,
        }

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if not force and self._cached_snapshot and now - self._cached_at < 4:
                return copy.deepcopy(self._cached_snapshot)
            if self.settings.demo:
                value = self._demo_snapshot()
            else:
                try:
                    value = json.loads(self._command("snapshot", timeout=30))
                except json.JSONDecodeError as exc:
                    raise OpsError("状态数据格式错误") from exc
            self._cached_snapshot = value
            self._cached_at = now
            return copy.deepcopy(value)

    def action(self, project_id: str, component_id: str, action: str) -> dict[str, Any]:
        _, component = find_project_component(self.config, project_id, component_id)
        if action not in component.get("actions", []):
            raise OpsError("该组件不允许执行此操作")
        if self.settings.demo:
            result = {"ok": True, "message": f"演示模式：{action} 已完成"}
        else:
            try:
                result = json.loads(
                    self._command("action", project_id, component_id, action, timeout=100)
                )
            except json.JSONDecodeError as exc:
                raise OpsError("操作结果格式错误") from exc
        with self._lock:
            self._cached_snapshot = None
            self._cached_at = 0
        return result

    def logs(self, project_id: str, component_id: str, lines: int) -> str:
        find_project_component(self.config, project_id, component_id)
        safe_lines = max(20, min(lines, 1000))
        if self.settings.demo:
            now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
            return "\n".join(
                f"{now} {project_id}/{component_id}[{1400 + index}]: service heartbeat ok"
                for index in range(min(safe_lines, 24))
            )
        return self._command("logs", project_id, component_id, str(safe_lines), timeout=30)
