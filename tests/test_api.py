from __future__ import annotations

from app.main import create_app
from fastapi.testclient import TestClient


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
