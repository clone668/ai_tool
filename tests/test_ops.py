from __future__ import annotations

import pytest
from app.ops import OpsClient, OpsError


def test_demo_snapshot_matches_managed_projects(demo_settings) -> None:
    client = OpsClient(demo_settings)

    snapshot = client.snapshot()

    assert snapshot["host"]["address"] == "192.168.2.240"
    assert snapshot["summary"]["total"] == 9
    assert len(snapshot["projects"]) == 11


def test_backend_rejects_disallowed_component_action(demo_settings) -> None:
    client = OpsClient(demo_settings)

    with pytest.raises(OpsError, match="不允许"):
        client.action("jx2", "nginx", "restart")


def test_demo_logs_are_bounded(demo_settings) -> None:
    client = OpsClient(demo_settings)

    output = client.logs("editor-3d", "editor", 5000)

    assert "editor-3d/editor" in output
    assert len(output.splitlines()) == 24
