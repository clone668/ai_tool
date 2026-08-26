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
    args = parser.parse_args(
        ["startup-action", "docker", "open-webui", "policy", "unless-stopped"]
    )
    assert args.scope == "docker"
    assert args.value == "unless-stopped"
