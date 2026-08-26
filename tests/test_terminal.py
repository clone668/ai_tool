from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from app.terminal import (
    SHELL_COMMAND,
    TERMINAL_RCFILE,
    TERMINAL_USER,
    _read_pty,
    _write_pty,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_terminal_command_matches_sudoers_allowlist() -> None:
    command_start = SHELL_COMMAND.index("--") + 1
    allowed_command = " ".join(SHELL_COMMAND[command_start:])
    sudoers = (ROOT_DIR / "deploy" / "ai-tool.sudoers").read_text(encoding="utf-8")

    assert SHELL_COMMAND[:6] == (
        "/usr/bin/sudo",
        "-n",
        "-H",
        "-u",
        TERMINAL_USER,
        "--",
    )
    assert f"ai-tool ALL=({TERMINAL_USER}) NOPASSWD: {allowed_command}" in sudoers


def test_terminal_uses_managed_interactive_bashrc() -> None:
    bashrc = (ROOT_DIR / "deploy" / "terminal.bashrc").read_text(encoding="utf-8")

    assert TERMINAL_RCFILE in SHELL_COMMAND
    assert "stty sane" in bashrc
    assert "checkwinsize" in bashrc
    assert "HISTFILE" in bashrc
    assert "PS1=" in bashrc


@pytest.mark.skipif(sys.platform == "win32", reason="PTY event loop targets Linux")
def test_nonblocking_terminal_io_round_trip() -> None:
    async def exercise() -> None:
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        os.set_blocking(write_fd, False)
        try:
            pending_read = asyncio.create_task(_read_pty(read_fd))
            await _write_pty(write_fd, b"terminal-ready")
            assert await pending_read == b"terminal-ready"
        finally:
            os.close(read_fd)
            os.close(write_fd)

    asyncio.run(exercise())
