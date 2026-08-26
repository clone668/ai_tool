from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SERVICE_PATTERN = re.compile(r"^[A-Za-z0-9@_.:-]+\.service$")
USER_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
ALLOWED_COMPONENT_TYPES = {"systemd", "user_systemd", "compose", "cron"}
ALLOWED_ACTIONS = {"start", "restart", "stop"}


class ConfigurationError(RuntimeError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    config_path: Path
    data_dir: Path
    static_dir: Path
    ops_helper: Path
    demo: bool
    cookie_secure: bool
    session_hours: int
    password_hash: str | None
    demo_password: str | None
    terminal_enabled: bool = True
    terminal_home: Path | None = None

    @classmethod
    def from_env(cls) -> Settings:
        demo = _env_bool("AI_TOOL_DEMO")
        data_dir = Path(os.getenv("AI_TOOL_DATA_DIR", str(ROOT_DIR / ".data")))
        return cls(
            config_path=Path(
                os.getenv("AI_TOOL_CONFIG", str(ROOT_DIR / "config" / "projects.json"))
            ),
            data_dir=data_dir,
            static_dir=Path(os.getenv("AI_TOOL_STATIC_DIR", str(ROOT_DIR / "frontend" / "dist"))),
            ops_helper=Path(os.getenv("AI_TOOL_OPS_HELPER", "/usr/local/libexec/ai-tool-ops")),
            demo=demo,
            cookie_secure=_env_bool("AI_TOOL_COOKIE_SECURE"),
            session_hours=max(1, min(int(os.getenv("AI_TOOL_SESSION_HOURS", "12")), 168)),
            password_hash=os.getenv("AI_TOOL_PASSWORD_HASH"),
            demo_password=os.getenv("AI_TOOL_PASSWORD") if demo else None,
            terminal_enabled=_env_bool("AI_TOOL_TERMINAL_ENABLED", True),
            terminal_home=Path(
                os.getenv("AI_TOOL_TERMINAL_HOME", str(data_dir / "terminal-home"))
            ),
        )


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ConfigurationError(f"{label} must match {ID_PATTERN.pattern}")
    return value


def _require_absolute_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not PurePosixPath(value).is_absolute():
        raise ConfigurationError(f"{label} must be an absolute path")
    return value


def _validate_component(component: dict[str, Any], project_id: str) -> None:
    component_id = _require_id(component.get("id"), f"{project_id}.component.id")
    component_type = component.get("type")
    if component_type not in ALLOWED_COMPONENT_TYPES:
        raise ConfigurationError(f"unsupported component type: {component_type}")

    actions = component.get("actions", [])
    if not isinstance(actions, list) or not set(actions).issubset(ALLOWED_ACTIONS):
        raise ConfigurationError(f"invalid actions for {project_id}/{component_id}")

    if component_type in {"systemd", "user_systemd"}:
        service = component.get("service")
        if not isinstance(service, str) or not SERVICE_PATTERN.fullmatch(service):
            raise ConfigurationError(f"invalid service for {project_id}/{component_id}")

    if component_type == "user_systemd":
        user = component.get("user")
        if not isinstance(user, str) or not USER_PATTERN.fullmatch(user):
            raise ConfigurationError(f"invalid user for {project_id}/{component_id}")

    if component_type == "compose":
        compose_file = _require_absolute_path(
            component.get("compose_file"), f"{project_id}/{component_id}.compose_file"
        )
        if not compose_file.startswith("/data/"):
            raise ConfigurationError("compose files must be located under /data")
        containers = component.get("containers")
        if (
            not isinstance(containers, list)
            or not containers
            or not all(isinstance(name, str) and ID_PATTERN.fullmatch(name) for name in containers)
        ):
            raise ConfigurationError(f"invalid containers for {project_id}/{component_id}")

    if component_type == "cron":
        _require_absolute_path(component.get("command"), f"{project_id}/{component_id}.command")
        _require_absolute_path(component.get("log_path"), f"{project_id}/{component_id}.log_path")


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    host = config.get("host")
    projects = config.get("projects")
    if not isinstance(host, dict) or not isinstance(projects, list):
        raise ConfigurationError("configuration requires host and projects")
    _require_id(host.get("id"), "host.id")

    seen_projects: set[str] = set()
    for project in projects:
        if not isinstance(project, dict):
            raise ConfigurationError("each project must be an object")
        project_id = _require_id(project.get("id"), "project.id")
        if project_id in seen_projects:
            raise ConfigurationError(f"duplicate project id: {project_id}")
        seen_projects.add(project_id)
        components = project.get("components")
        if not isinstance(components, list) or not components:
            raise ConfigurationError(f"project {project_id} has no components")
        seen_components: set[str] = set()
        for component in components:
            _validate_component(component, project_id)
            component_id = component["id"]
            if component_id in seen_components:
                raise ConfigurationError(f"duplicate component id: {project_id}/{component_id}")
            seen_components.add(component_id)
    return config


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot load configuration: {path}") from exc
    if not isinstance(config, dict):
        raise ConfigurationError("configuration root must be an object")
    return validate_config(config)


def find_project_component(
    config: dict[str, Any], project_id: str, component_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    for project in config["projects"]:
        if project["id"] != project_id:
            continue
        for component in project["components"]:
            if component["id"] == component_id:
                return project, component
        break
    raise KeyError(f"unknown component: {project_id}/{component_id}")
