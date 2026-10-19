from __future__ import annotations

from contextlib import suppress

import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "dev-password"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return response.json()


def test_authentication_and_dashboard(demo_settings) -> None:
    with TestClient(create_app(demo_settings)) as client:
        assert client.get("/api/dashboard").status_code == 401

        invalid = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "incorrect-password"},
        )
        assert invalid.status_code == 401

        session = login(client)
        assert session["username"] == "admin"
        assert client.get("/api/auth/session").status_code == 200

        dashboard = client.get("/api/dashboard")
        assert dashboard.status_code == 200
        payload = dashboard.json()
        assert payload["host"]["hostname"] == "huxi-H81M"
        assert payload["summary"]["total"] == 11


def test_csrf_actions_and_audit(demo_settings) -> None:
    with TestClient(create_app(demo_settings)) as client:
        session = login(client)

        missing_csrf = client.post(
            "/api/projects/editor-3d/actions",
            json={"component_id": "editor", "action": "restart"},
        )
        assert missing_csrf.status_code == 403

        completed = client.post(
            "/api/projects/editor-3d/actions",
            json={"component_id": "editor", "action": "restart"},
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert completed.status_code == 200

        disallowed = client.post(
            "/api/projects/jx2/actions",
            json={"component_id": "nginx", "action": "restart"},
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert disallowed.status_code == 400

        audit = client.get("/api/audit").json()["items"]
        assert any(
            item["project_id"] == "editor-3d" and item["outcome"] == "success" for item in audit
        )
        assert any(item["project_id"] == "jx2" and item["outcome"] == "failed" for item in audit)


def test_logs_logout_and_origin_check(demo_settings) -> None:
    with TestClient(create_app(demo_settings)) as client:
        rejected_origin = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "dev-password"},
            headers={"Origin": "http://evil.example"},
        )
        assert rejected_origin.status_code == 403

        session = login(client)
        logs = client.get("/api/projects/openclaw/components/gateway/logs?lines=100")
        assert logs.status_code == 200
        assert "openclaw/gateway" in logs.json()["content"]

        logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": session["csrf_token"]})
        assert logout.status_code == 200
        assert client.get("/api/dashboard").status_code == 401


def test_management_inventory_endpoints(demo_settings) -> None:
    with TestClient(create_app(demo_settings)) as client:
        session = login(client)
        assert session["terminal_enabled"] is True

        software = client.get("/api/software?query=nginx").json()
        assert software["items"][0]["name"] == "nginx"
        assert client.get("/api/startup").json()["total"] >= 4

        system = client.get("/api/system").json()
        assert system["cpu"]["cores"] == 4
        assert system["filesystems"][1]["mountpoint"] == "/data"
        assert len(system["history"]) == 1

        storage = client.get("/api/storage").json()
        assert storage["disks"][0]["smart"]["passed"] is True
        assert storage["filesystems"][1]["mountpoint"] == "/data"

        scan = client.get("/api/storage/scan?path=/data").json()
        assert scan["entries"]
        assert client.get("/api/storage/scan?path=/data/../etc").status_code == 400

        shares = client.get("/api/shares").json()
        assert shares["items"][0]["id"] == "media"
        assert shares["samba_available"] is True

        saved = client.put(
            "/api/shares/media",
            json={"id": "media", "comment": "媒体库", "path": "/data/media",
                  "valid_users": ["huxi"]},
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert saved.status_code == 200
        denied = client.put(
            "/api/shares/media",
            json={"id": "media", "comment": "媒体库", "path": "/data/media"},
        )
        assert denied.status_code == 403

        maintenance = client.get("/api/maintenance").json()
        assert any(
            item["id"] == "docker-volumes" and item["actionable"] is False
            for item in maintenance["cleanup"]["candidates"]
        )
        web_services = client.get("/api/web-services").json()
        assert web_services["nginx_active"] is True
        assert web_services["warnings"] == []
        assert web_services["discovered"][0]["source"] == "nginx"
        assert web_services["discovered"][1]["suggested_service"]["upstream_port"] == 3003

        external_upstream = client.put(
            "/api/web-services/example",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json={
                "id": "example",
                "name": "External upstream",
                "domain": "example.local",
                "upstream_host": "192.168.2.10",
                "upstream_port": 8080,
                "websocket": False,
                "enabled": True,
            },
        )
        assert external_upstream.status_code == 422


def test_management_actions_require_csrf_and_are_audited(demo_settings) -> None:
    with TestClient(create_app(demo_settings)) as client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"]}

        denied = client.post(
            "/api/software/actions",
            json={"manager": "apt", "name": "nginx", "action": "upgrade"},
        )
        assert denied.status_code == 403

        plan = client.post(
            "/api/software/plan",
            headers=headers,
            json={"manager": "apt", "name": "nginx", "action": "upgrade"},
        )
        assert plan.status_code == 200
        assert plan.json()["action"] == "upgrade"

        remove_plan = client.post(
            "/api/software/plan",
            headers=headers,
            json={"manager": "apt", "name": "nginx", "action": "remove"},
        ).json()
        stale_remove = client.post(
            "/api/software/actions",
            headers=headers,
            json={"manager": "apt", "name": "nginx", "action": "remove"},
        )
        assert stale_remove.status_code == 409
        confirmed_remove = client.post(
            "/api/software/actions",
            headers=headers,
            json={
                "manager": "apt",
                "name": "nginx",
                "action": "remove",
                "confirmation_token": remove_plan["confirmation_token"],
            },
        )
        assert confirmed_remove.status_code == 200
        replayed_remove = client.post(
            "/api/software/actions",
            headers=headers,
            json={
                "manager": "apt",
                "name": "nginx",
                "action": "remove",
                "confirmation_token": remove_plan["confirmation_token"],
            },
        )
        assert replayed_remove.status_code == 409

        startup = client.post(
            "/api/startup/actions",
            headers=headers,
            json={
                "scope": "docker",
                "name": "open-webui",
                "action": "policy",
                "value": "unless-stopped",
            },
        )
        assert startup.status_code == 200

        maintenance = client.get("/api/maintenance").json()
        apt_cache = next(
            item for item in maintenance["cleanup"]["candidates"] if item["id"] == "apt-cache"
        )
        cleanup = client.post(
            "/api/maintenance/actions",
            headers=headers,
            json={
                "action": "apt-cache",
                "confirmation_token": apt_cache["confirmation_token"],
            },
        )
        assert cleanup.status_code == 200

        invalid_package = client.post(
            "/api/software/plan",
            headers=headers,
            json={"manager": "apt", "name": "bad\npackage", "action": "install"},
        )
        assert invalid_package.status_code == 422

        audit = client.get("/api/audit").json()["items"]
        assert any(item["action"] == "startup.policy" for item in audit)
        assert any(item["action"] == "maintenance.apt-cache" for item in audit)
        assert any(
            item["action"] == "software.remove" and item["outcome"] == "denied"
            for item in audit
        )


def test_terminal_websocket_rejects_cross_origin(demo_settings) -> None:
    with TestClient(create_app(demo_settings)) as client:
        with pytest.raises(WebSocketDisconnect) as rejected, client.websocket_connect(
            "/api/terminal/ws",
            headers={"Origin": "http://evil.example"},
        ):
            pass
        assert rejected.value.code == 1008


def test_terminal_websocket_allows_only_one_active_session(demo_settings, monkeypatch) -> None:
    async def hold_terminal(websocket, _home) -> None:
        with suppress(WebSocketDisconnect):
            await websocket.receive_text()

    monkeypatch.setattr("app.main.serve_terminal", hold_terminal)

    with TestClient(create_app(demo_settings)) as client:
        login(client)
        headers = {"Origin": "http://testserver"}
        with client.websocket_connect("/api/terminal/ws", headers=headers):
            with pytest.raises(WebSocketDisconnect) as rejected, client.websocket_connect(
                "/api/terminal/ws", headers=headers
            ):
                pass
            assert rejected.value.code == 1013

        audit = client.get("/api/audit").json()["items"]
        assert any(
            item["action"] == "terminal.connect" and item["outcome"] == "denied"
            for item in audit
        )
