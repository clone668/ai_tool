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
