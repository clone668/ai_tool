from __future__ import annotations

import base64
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

    def _json_command(self, *arguments: str, timeout: int = 60) -> dict[str, Any]:
        try:
            value = json.loads(self._command(*arguments, timeout=timeout))
        except json.JSONDecodeError as exc:
            raise OpsError("操作结果格式错误") from exc
        if not isinstance(value, dict):
            raise OpsError("操作结果格式错误")
        return value

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

    def software(self, query: str, limit: int = 200) -> dict[str, Any]:
        if self.settings.demo:
            items = [
                {
                    "manager": "apt",
                    "name": "nginx",
                    "version": "1.24.0-2ubuntu7.5",
                    "architecture": "amd64",
                    "size_bytes": 1_900_000,
                    "installed": True,
                    "description": "high performance web server",
                    "protected": False,
                },
                {
                    "manager": "apt",
                    "name": "openssh-server",
                    "version": "1:9.6p1-3ubuntu13.14",
                    "architecture": "amd64",
                    "size_bytes": 2_100_000,
                    "installed": True,
                    "description": "secure shell server",
                    "protected": True,
                },
                {
                    "manager": "snap",
                    "name": "certbot",
                    "version": "4.1.1",
                    "revision": "5000",
                    "tracking": "latest/stable",
                    "size_bytes": None,
                    "installed": True,
                    "description": "Snap package",
                    "protected": False,
                },
            ]
            normalized = query.strip().lower()
            if normalized:
                items = [item for item in items if normalized in item["name"]]
            return {
                "query": query,
                "items": items[:limit],
                "counts": {
                    "installed": sum(bool(item["installed"]) for item in items),
                    "available": sum(not item["installed"] for item in items),
                },
                "managers": {"apt": True, "snap": True},
            }
        return self._json_command("software", query, str(limit), timeout=70)

    def software_plan(self, manager: str, name: str, action: str) -> dict[str, Any]:
        if self.settings.demo:
            return {
                "manager": manager,
                "name": name,
                "action": action,
                "changes": [f"{action}: {name}"],
                "summary": "演示模式：不会修改系统。",
            }
        return self._json_command("software-plan", manager, name, action, timeout=80)

    def software_action(self, manager: str, name: str, action: str) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：{manager} {action} {name} 已完成"}
        return self._json_command(
            "software-action", manager, name, action, timeout=920
        )

    def startup(self, query: str, limit: int = 500) -> dict[str, Any]:
        if self.settings.demo:
            items = [
                {
                    "scope": "system",
                    "name": "nginx.service",
                    "enabled_state": "enabled",
                    "active_state": "active",
                    "substate": "running",
                    "protected": False,
                },
                {
                    "scope": "system",
                    "name": "ai-tool.service",
                    "enabled_state": "enabled",
                    "active_state": "active",
                    "substate": "running",
                    "protected": True,
                },
                {
                    "scope": "user",
                    "name": "openclaw-gateway.service",
                    "enabled_state": "enabled",
                    "active_state": "inactive",
                    "substate": "dead",
                    "protected": False,
                },
                {
                    "scope": "docker",
                    "name": "open-webui",
                    "enabled_state": "unless-stopped",
                    "active_state": "running",
                    "substate": "healthy",
                    "protected": False,
                },
            ]
            normalized = query.strip().lower()
            if normalized:
                items = [item for item in items if normalized in item["name"]]
            return {"items": items[:limit], "total": len(items)}
        return self._json_command("startup", query, str(limit), timeout=80)

    def startup_action(
        self, scope: str, name: str, action: str, value: str = "_"
    ) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：{name} {action} 已完成"}
        return self._json_command(
            "startup-action", scope, name, action, value, timeout=110
        )

    def system_details(self) -> dict[str, Any]:
        if self.settings.demo:
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "cpu": {
                    "model": "Intel(R) Core(TM) i5-4590 CPU @ 3.30GHz",
                    "cores": 4,
                    "percent": 18.4,
                    "load_average": [0.42, 0.36, 0.31],
                    "temperatures": [{"label": "x86_pkg_temp", "celsius": 47.0}],
                },
                "memory": {
                    "total": 16 * 1024**3,
                    "available": 9.7 * 1024**3,
                    "used": 6.3 * 1024**3,
                    "percent": 39.4,
                    "cached": 3.1 * 1024**3,
                    "buffers": 220 * 1024**2,
                    "swap_total": 2 * 1024**3,
                    "swap_used": 80 * 1024**2,
                    "swap_percent": 3.9,
                },
                "filesystems": [
                    {
                        "source": "/dev/sda2",
                        "fstype": "ext4",
                        "mountpoint": "/",
                        "size": 120 * 1024**3,
                        "used": 42 * 1024**3,
                        "available": 78 * 1024**3,
                        "percent": 35.0,
                        "inodes": 7_800_000,
                        "inodes_used": 430_000,
                        "inodes_percent": 6.0,
                    },
                    {
                        "source": "/dev/sdb1",
                        "fstype": "ext4",
                        "mountpoint": "/data",
                        "size": 1.8 * 1024**4,
                        "used": 412 * 1024**3,
                        "available": 1.4 * 1024**4,
                        "percent": 22.0,
                        "inodes": 122_000_000,
                        "inodes_used": 1_800_000,
                        "inodes_percent": 2.0,
                    },
                ],
                "block_devices": [],
                "processes": [
                    {
                        "pid": 1882,
                        "user": "root",
                        "command": "dockerd",
                        "cpu_percent": 4.2,
                        "memory_percent": 2.1,
                        "rss_bytes": 352 * 1024**2,
                        "state": "Ssl",
                    },
                    {
                        "pid": 4312,
                        "user": "huxi",
                        "command": "node",
                        "cpu_percent": 2.8,
                        "memory_percent": 3.4,
                        "rss_bytes": 570 * 1024**2,
                        "state": "Sl",
                    },
                ],
                "containers": [
                    {
                        "name": "open-webui",
                        "cpu": "1.24%",
                        "memory": "1.1GiB / 16GiB",
                        "memory_percent": "6.9%",
                        "network": "28MB / 14MB",
                        "block_io": "120MB / 8MB",
                        "pids": "34",
                    }
                ],
                "network": [
                    {
                        "interface": "enp3s0",
                        "received_bytes": 13_800_000_000,
                        "received_packets": 18_200_000,
                        "received_errors": 0,
                        "sent_bytes": 8_400_000_000,
                        "sent_packets": 12_100_000,
                        "sent_errors": 0,
                    }
                ],
                "uptime_seconds": 192_420,
                "failed_units": 1,
                "smart_available": True,
            }
        return self._json_command("system-details", timeout=80)

    def storage_details(self) -> dict[str, Any]:
        if self.settings.demo:
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "filesystems": self.system_details()["filesystems"],
                "disks": [
                    {
                        "name": "sda",
                        "path": "/dev/sda",
                        "model": "CT240BX500SSD1",
                        "serial": "2415E8A0B1C2",
                        "size": 240 * 1024**3,
                        "rota": False,
                        "tran": "sata",
                        "smart": {
                            "available": True,
                            "passed": True,
                            "temperature_celsius": 38,
                            "power_on_hours": 21840,
                        },
                    },
                    {
                        "name": "sdb",
                        "path": "/dev/sdb",
                        "model": "ST2000DM008-2FR102",
                        "serial": "ZFL3H2KA",
                        "size": 2 * 1024**4,
                        "rota": True,
                        "tran": "sata",
                        "smart": {
                            "available": True,
                            "passed": True,
                            "temperature_celsius": 34,
                            "power_on_hours": 30210,
                        },
                    },
                ],
                "partitions": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "fstype": "ext4",
                        "label": "data",
                        "size": 200 * 1024**3,
                        "mountpoints": ["/data"],
                    },
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "fstype": "ext4",
                        "label": None,
                        "size": 1024**4,
                        "mountpoints": [],
                    },
                ],
                "swap": [
                    {
                        "name": "/swapfile",
                        "type": "file",
                        "size": 2 * 1024**3,
                        "used": 80 * 1024**2,
                        "priority": -2,
                    }
                ],
                "smart_available": True,
            }
        return self._json_command("storage-details", timeout=90)

    def storage_scan(self, path: str) -> dict[str, Any]:
        if self.settings.demo:
            entries = [
                ("backups", 386 * 1024**3),
                ("docker", 18 * 1024**3),
                ("media", 6.2 * 1024**3),
                ("projects", 1.8 * 1024**3),
                ("logs", 460 * 1024**2),
            ]
            base = path.rstrip("/") or "/data"
            return {
                "path": path,
                "total_bytes": sum(size for _, size in entries),
                "entries": [
                    {"path": f"{base}/{name}", "name": name, "size_bytes": int(size)}
                    for name, size in entries
                ],
            }
        return self._json_command("storage-scan", path, timeout=200)

    def storage_mount(
        self, device: str, mount_point: str, persist: bool
    ) -> dict[str, Any]:
        if self.settings.demo:
            suffix = "，并写入 fstab" if persist else ""
            return {"ok": True, "message": f"演示模式：{device} 已挂载到 {mount_point}{suffix}"}
        extra = ["--persist"] if persist else []
        return self._json_command("storage-mount", device, mount_point, *extra, timeout=90)

    def storage_umount(self, mount_point: str) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：{mount_point} 已卸载"}
        return self._json_command("storage-umount", mount_point, timeout=90)

    def storage_format(self, device: str, fstype: str, label: str) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：{device} 已格式化为 {fstype}"}
        return self._json_command("storage-format", device, fstype, label, timeout=360)

    def share_inventory(self) -> dict[str, Any]:
        if self.settings.demo:
            return {
                "items": [
                    {
                        "id": "media",
                        "comment": "媒体库",
                        "path": "/data/media",
                        "read_only": False,
                        "browseable": True,
                        "guest_ok": False,
                        "valid_users": ["huxi"],
                        "enabled": True,
                    },
                    {
                        "id": "backup-drop",
                        "comment": "备份投递",
                        "path": "/data/backups/drop",
                        "read_only": True,
                        "browseable": True,
                        "guest_ok": False,
                        "valid_users": [],
                        "enabled": False,
                    },
                ],
                "discovered": [
                    {
                        "name": "oldshare",
                        "path": "/srv/oldshare",
                        "comment": "手动配置的共享",
                        "read_only": True,
                        "managed": False,
                    }
                ],
                "samba_available": True,
                "smbd_active": True,
                "share_roots": ["/data", "/srv", "/home"],
                "warnings": [],
            }
        return self._json_command("share-inventory", timeout=60)

    def share_upsert(self, share: dict[str, Any]) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：共享 {share['id']} 已保存"}
        payload = base64.urlsafe_b64encode(
            json.dumps(share, ensure_ascii=False).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return self._json_command("share-upsert", payload, timeout=100)

    def share_action(self, share_id: str, action: str) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：共享 {share_id} {action} 已完成"}
        return self._json_command("share-action", share_id, action, timeout=100)

    def maintenance_scan(self) -> dict[str, Any]:
        if self.settings.demo:
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "candidates": [
                    {
                        "id": "apt-cache",
                        "label": "APT 下载缓存",
                        "risk": "safe",
                        "size_bytes": 780 * 1024**2,
                        "detail": "/var/cache/apt/archives",
                    },
                    {
                        "id": "journal-14d",
                        "label": "14 天前的系统日志",
                        "risk": "safe",
                        "size_bytes": None,
                        "detail": "Archived and active journals take up 1.2G",
                    },
                    {
                        "id": "docker-build-cache",
                        "label": "Docker 构建缓存",
                        "risk": "medium",
                        "size_bytes": None,
                        "detail": "2.4GB reclaimable",
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
                "docker": [],
            }
        return self._json_command("maintenance-scan", timeout=100)

    def maintenance_action(self, action: str) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：清理 {action} 已完成"}
        return self._json_command("maintenance-action", action, timeout=920)

    def optimization_scan(self) -> dict[str, Any]:
        if self.settings.demo:
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "recommendations": [
                    {
                        "id": "enable-fstrim",
                        "label": "启用定期 SSD/TRIM",
                        "status": "applied",
                        "detail": "enabled=enabled active=active",
                        "reversible": True,
                    },
                    {
                        "id": "limit-journal",
                        "label": "限制 systemd journal 占用",
                        "status": "recommended",
                        "detail": "SystemMaxUse=500M, RuntimeMaxUse=200M",
                        "reversible": True,
                    },
                ],
                "facts": {"swappiness": 60, "reboot_required": False, "updates": 8},
            }
        return self._json_command("optimization-scan", timeout=100)

    def optimization_action(self, action: str) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：优化 {action} 已完成"}
        return self._json_command("optimization-action", action, timeout=100)

    def web_inventory(self) -> dict[str, Any]:
        if self.settings.demo:
            return {
                "items": [
                    {
                        "id": "openclaw-home",
                        "name": "OpenClaw Home",
                        "domain": "home.entroscav.com",
                        "upstream_host": "127.0.0.1",
                        "upstream_port": 18789,
                        "websocket": True,
                        "enabled": True,
                        "upstream_healthy": False,
                    }
                ],
                "discovered": [
                    {
                        "id": "nginx-home-entroscav-com-80",
                        "name": "OpenClaw Home",
                        "url": "http://home.entroscav.com",
                        "domain": "home.entroscav.com",
                        "port": 80,
                        "protocol": "http",
                        "source": "nginx",
                        "source_detail": "/etc/nginx/sites-enabled/openclaw-home",
                        "exposure": "lan",
                        "healthy": True,
                        "status_code": 200,
                        "managed": True,
                        "suggested_service": None,
                        "upstream_host": "127.0.0.1",
                        "upstream_port": 18789,
                    },
                    {
                        "id": "direct-open-webui-3003",
                        "name": "Open WebUI",
                        "url": "http://192.168.2.240:3003",
                        "domain": None,
                        "port": 3003,
                        "protocol": "http",
                        "source": "docker",
                        "source_detail": "open-webui",
                        "exposure": "lan",
                        "healthy": True,
                        "status_code": 200,
                        "managed": False,
                        "suggested_service": {
                            "id": "open-webui",
                            "name": "Open WebUI",
                            "domain": "",
                            "upstream_host": "127.0.0.1",
                            "upstream_port": 3003,
                            "websocket": True,
                            "enabled": True,
                        },
                        "upstream_host": "127.0.0.1",
                        "upstream_port": 3003,
                    },
                ],
                "nginx_active": True,
                "warnings": [],
            }
        return self._json_command("web-inventory", timeout=80)

    def web_upsert(self, service: dict[str, Any]) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：{service['id']} 已保存"}
        payload = base64.urlsafe_b64encode(
            json.dumps(service, ensure_ascii=False).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return self._json_command("web-upsert", payload, timeout=100)

    def web_action(self, service_id: str, action: str) -> dict[str, Any]:
        if self.settings.demo:
            return {"ok": True, "message": f"演示模式：{service_id} {action} 已完成"}
        return self._json_command("web-action", service_id, action, timeout=100)

    def web_logs(self, service_id: str, stream: str, lines: int) -> str:
        safe_lines = max(20, min(lines, 1000))
        if self.settings.demo:
            now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
            return "\n".join(
                f'{now} 192.168.2.10 "GET / HTTP/1.1" 200 842 "{service_id}/{stream}"'
                for _ in range(min(safe_lines, 16))
            )
        return self._command(
            "web-logs", service_id, stream, str(safe_lines), timeout=30
        )
