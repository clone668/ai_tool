from __future__ import annotations

import sys

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="helper targets Linux")
def test_privileged_helper_rejects_unlisted_actions(monkeypatch) -> None:
    from deploy.ai_tool_ops import OpsFailure, load_config, perform_action

    monkeypatch.setattr("deploy.ai_tool_ops.CONFIG_PATH", None)
    config = load_config(__import__("pathlib").Path("config/projects.json"))

    with pytest.raises(OpsFailure, match="not allowed"):
        perform_action(config, "jx2", "nginx", "restart")
