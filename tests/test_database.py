from __future__ import annotations

from pathlib import Path

from app.database import Database


def test_sessions_and_audit_are_persisted(tmp_path: Path) -> None:
    database = Database(tmp_path / "ai-tool.db")
    database.initialize()

    session = database.create_session("admin", "127.0.0.1", "pytest", 12)
    stored = database.get_session(session.token)
    assert stored is not None
    assert stored["username"] == "admin"
    assert stored["csrf_token"] == session.csrf_token

    database.record_audit(
        username="admin",
        ip_address="127.0.0.1",
        project_id="editor-3d",
        component_id="editor",
        action="restart",
        outcome="success",
        detail="completed",
    )
    audit = database.list_audit()
    assert audit[0]["project_id"] == "editor-3d"
    assert audit[0]["outcome"] == "success"

    database.record_system_metrics(
        cpu_percent=12.5,
        memory_percent=38.2,
        load_one=0.42,
        disk_percent=21.0,
    )
    metrics = database.list_system_metrics()
    assert metrics == [
        {
            "created_at": metrics[0]["created_at"],
            "cpu_percent": 12.5,
            "memory_percent": 38.2,
            "load_one": 0.42,
            "disk_percent": 21.0,
        }
    ]

    confirmation = database.create_confirmation("software.remove", "apt:nginx")
    assert database.consume_confirmation(confirmation, "software.remove", "apt:nginx")
    assert not database.consume_confirmation(confirmation, "software.remove", "apt:nginx")

    database.delete_session(session.token)
    assert database.get_session(session.token) is None
