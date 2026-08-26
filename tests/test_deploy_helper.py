from __future__ import annotations

import sys
from subprocess import CompletedProcess

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_privileged_helper_rejects_unlisted_actions(monkeypatch) -> None:
    from deploy.ai_tool_ops import OpsFailure, load_config, perform_action

    monkeypatch.setattr("deploy.ai_tool_ops.CONFIG_PATH", None)
    config = load_config(__import__("pathlib").Path("config/projects.json"))

    with pytest.raises(OpsFailure, match="not allowed"):
        perform_action(config, "jx2", "nginx", "restart")


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_software_plan_rejects_protected_dependency_removal(monkeypatch) -> None:
    from deploy.ai_tool_ops import OpsFailure, software_plan

    monkeypatch.setattr(
        "deploy.ai_tool_ops.run",
        lambda *args, **kwargs: CompletedProcess(
            [], 0, "Remv systemd [255.4-1ubuntu8]\n", ""
        ),
    )

    with pytest.raises(OpsFailure, match="protected"):
        software_plan("apt", "example-package", "install")


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_privileged_helper_exposes_only_structured_management_commands() -> None:
    from deploy.ai_tool_ops import build_parser

    parser = build_parser()
    assert parser.parse_args(["system-details"]).command == "system-details"
    assert parser.parse_args(["terminal-cleanup"]).command == "terminal-cleanup"
    with pytest.raises(SystemExit):
        parser.parse_args(["terminal-cleanup", "1000"])
    args = parser.parse_args(
        ["startup-action", "docker", "open-webui", "policy", "unless-stopped"]
    )
    assert args.scope == "docker"
    assert args.value == "unless-stopped"


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_terminal_cleanup_targets_only_fixed_terminal_user(monkeypatch) -> None:
    from deploy import ai_tool_ops

    looked_up: list[str] = []
    terminated_uids: list[int] = []

    def fake_getpwnam(username: str):
        looked_up.append(username)
        return type("User", (), {"pw_uid": 4242})()

    def fake_terminate(uid: int) -> dict[str, int]:
        terminated_uids.append(uid)
        return {"matched": 2, "killed": 1, "remaining": 0}

    monkeypatch.setattr(ai_tool_ops.pwd, "getpwnam", fake_getpwnam)
    monkeypatch.setattr(ai_tool_ops, "_terminate_uid_processes", fake_terminate)

    result = ai_tool_ops.terminal_cleanup()

    assert looked_up == ["ai-tool-shell"]
    assert terminated_uids == [4242]
    assert result == {
        "ok": True,
        "user": "ai-tool-shell",
        "matched": 2,
        "killed": 1,
        "remaining": 0,
    }


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_terminal_cleanup_fails_when_terminal_user_is_unavailable(monkeypatch) -> None:
    from deploy import ai_tool_ops

    def missing_user(_: str):
        raise KeyError

    monkeypatch.setattr(ai_tool_ops.pwd, "getpwnam", missing_user)

    with pytest.raises(ai_tool_ops.OpsFailure, match="terminal system user does not exist"):
        ai_tool_ops.terminal_cleanup()


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_terminal_cleanup_rejects_root_uid(monkeypatch) -> None:
    from deploy import ai_tool_ops

    root_user = type("User", (), {"pw_uid": 0})()
    monkeypatch.setattr(ai_tool_ops.pwd, "getpwnam", lambda _: root_user)

    with pytest.raises(ai_tool_ops.OpsFailure, match="unsafe UID"):
        ai_tool_ops.terminal_cleanup()


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_nginx_discovery_preserves_external_config_ownership(monkeypatch) -> None:
    from deploy import ai_tool_ops

    nginx_output = """# configuration file /etc/nginx/sites-enabled/default:
server {
    listen 80 default_server;
    server_name _;
    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }
}
# configuration file /etc/nginx/sites-enabled/openclaw-home:
server {
    listen 80;
    server_name home.entroscav.com;
    location / {
        proxy_pass http://127.0.0.1:18789;
    }
}
"""
    monkeypatch.setattr(
        ai_tool_ops,
        "_http_probe",
        lambda *args, **kwargs: {"detected": True, "healthy": True, "status_code": 200},
    )
    config = {
        "host": {"address": "192.168.2.240"},
        "projects": [
            {
                "id": "openclaw",
                "name": "OpenClaw Gateway",
                "checks": [
                    {"type": "http", "url": "http://127.0.0.1:18789"},
                ],
            }
        ],
    }

    discovered = ai_tool_ops._discover_nginx(nginx_output, config, [])

    assert len(discovered) == 2
    default = next(item for item in discovered if item["domain"] is None)
    openclaw = next(item for item in discovered if item["domain"] == "home.entroscav.com")
    assert default["name"] == "Nginx 默认站点"
    assert default["url"] == "http://192.168.2.240"
    assert openclaw["name"] == "OpenClaw Gateway"
    assert openclaw["source_detail"] == "/etc/nginx/sites-enabled/openclaw-home"
    assert openclaw["upstream_port"] == 18789
    assert openclaw["suggested_service"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_direct_discovery_filters_non_web_ports_and_builds_safe_suggestions(monkeypatch) -> None:
    from deploy import ai_tool_ops

    listeners = {
        3000: {
            "bind": "0.0.0.0",
            "port": 3000,
            "process": "docker-proxy",
            "pid": 10,
            "service": "docker.service",
        },
        3306: {
            "bind": "0.0.0.0",
            "port": 3306,
            "process": "mysqld",
            "pid": 11,
            "service": "mysql.service",
        },
        8788: {
            "bind": "0.0.0.0",
            "port": 8788,
            "process": "python",
            "pid": 12,
            "service": "smsi-archive-client.service",
        },
        19090: {
            "bind": "0.0.0.0",
            "port": 19090,
            "process": "uvicorn",
            "pid": 13,
            "service": "ai-tool.service",
        },
        43639: {
            "bind": "127.0.0.1",
            "port": 43639,
            "process": "containerd",
            "pid": 14,
            "service": "containerd.service",
        },
    }
    docker_ports = {3000: ["new-api"]}
    config = {
        "host": {"address": "192.168.2.240"},
        "projects": [
            {
                "id": "new-api",
                "name": "New API",
                "url": "http://192.168.2.240:3000",
                "checks": [],
            },
            {
                "id": "smsi-archive",
                "name": "SMSI Archive Client",
                "url": "http://192.168.2.240:8788",
                "checks": [],
            },
        ],
    }
    monkeypatch.setattr(
        ai_tool_ops,
        "_http_probe",
        lambda *args, **kwargs: {"detected": True, "healthy": True, "status_code": 200},
    )

    discovered = ai_tool_ops._discover_direct_services(
        config, listeners, docker_ports, []
    )

    assert {item["port"] for item in discovered} == {3000, 8788, 19090}
    new_api = next(item for item in discovered if item["port"] == 3000)
    archive = next(item for item in discovered if item["port"] == 8788)
    ai_tool = next(item for item in discovered if item["port"] == 19090)
    assert new_api["source"] == "docker"
    assert new_api["suggested_service"]["upstream_host"] == "127.0.0.1"
    assert archive["source"] == "systemd"
    assert ai_tool["name"] == "AI Tool"


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_managed_web_state_rejects_non_object_entries(tmp_path, monkeypatch) -> None:
    from deploy import ai_tool_ops

    state_path = tmp_path / "web-services.json"
    state_path.write_text('[{"id": "valid"}, "invalid"]', encoding="utf-8")
    monkeypatch.setattr(ai_tool_ops, "WEB_STATE_PATH", state_path)

    with pytest.raises(ai_tool_ops.OpsFailure, match="state is invalid"):
        ai_tool_ops._load_web_state()
