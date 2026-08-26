from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import WebSocket

TERMINAL_USER = "ai-tool-shell"
TERMINAL_RCFILE = "/etc/ai-tool/terminal.bashrc"
TERMINAL_CLEANUP_COMMAND = (
    "/usr/bin/sudo",
    "-n",
    "/usr/local/libexec/ai-tool-ops",
    "terminal-cleanup",
)
SHELL_COMMAND = (
    "/usr/bin/sudo",
    "-n",
    "-H",
    "-u",
    TERMINAL_USER,
    "--",
    "/bin/bash",
    "--noprofile",
    "--rcfile",
    TERMINAL_RCFILE,
    "-i",
)
LOGGER = logging.getLogger(__name__)


class TerminalUnavailable(RuntimeError):
    pass


def _resize_terminal(master_fd: int, rows: Any, cols: Any) -> None:
    import fcntl
    import struct
    import termios

    try:
        safe_rows = max(10, min(int(rows), 200))
        safe_cols = max(20, min(int(cols), 400))
    except (TypeError, ValueError):
        return
    size = struct.pack("HHHH", safe_rows, safe_cols, 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, size)


def _validate_terminal_home(home: Path) -> None:
    import pwd

    try:
        shell_user = pwd.getpwnam(TERMINAL_USER)
        home_stat = home.stat()
    except (KeyError, OSError) as exc:
        raise TerminalUnavailable("低权限终端账户或目录不可用") from exc
    if not home.is_dir() or home_stat.st_uid != shell_user.pw_uid:
        raise TerminalUnavailable("低权限终端目录权限无效")


def _start_shell(home: Path) -> tuple[int, int]:
    if os.name == "nt":
        raise TerminalUnavailable("Web 终端仅在 Linux 部署环境中可用")

    import pty

    _validate_terminal_home(home)
    environment = {
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TERM": "xterm-256color",
    }
    try:
        child_pid, master_fd = pty.fork()
    except OSError as exc:
        raise TerminalUnavailable("无法分配控制终端") from exc

    if child_pid == 0:
        try:
            os.chdir(home)
            os.execve(SHELL_COMMAND[0], SHELL_COMMAND, environment)
        except BaseException:
            with suppress(OSError):
                os.write(2, b"Unable to start the restricted terminal.\r\n")
            os._exit(126)
    return master_fd, child_pid


def _wait_for_child(child_pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            waited_pid, _ = os.waitpid(child_pid, os.WNOHANG)
        except ChildProcessError:
            return True
        if waited_pid == child_pid:
            return True
        if timeout <= 0 or time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return False


def _terminate_shell(child_pid: int) -> None:
    if _wait_for_child(child_pid, 0):
        return
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(child_pid, signal.SIGTERM)
    with suppress(ProcessLookupError, PermissionError):
        os.kill(child_pid, signal.SIGTERM)
    if _wait_for_child(child_pid, 2):
        return
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(child_pid, signal.SIGKILL)
    with suppress(ProcessLookupError, PermissionError):
        os.kill(child_pid, signal.SIGKILL)
    _wait_for_child(child_pid, 1)


def _cleanup_terminal_processes() -> None:
    try:
        result = subprocess.run(
            TERMINAL_CLEANUP_COMMAND,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env={"LANG": "C.UTF-8", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("terminal cleanup helper could not be executed") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise RuntimeError(detail or "terminal cleanup helper failed")


def _shutdown_terminal(child_pid: int) -> None:
    try:
        _cleanup_terminal_processes()
    except RuntimeError:
        LOGGER.warning("Privileged terminal process cleanup failed", exc_info=True)
    _terminate_shell(child_pid)


def _mark_ready(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


async def _read_pty(master_fd: int) -> bytes:
    loop = asyncio.get_running_loop()
    while True:
        readable = loop.create_future()
        loop.add_reader(master_fd, _mark_ready, readable)
        try:
            await readable
            return os.read(master_fd, 4096)
        except BlockingIOError:
            continue
        finally:
            loop.remove_reader(master_fd)


async def _write_pty(master_fd: int, data: bytes) -> None:
    loop = asyncio.get_running_loop()
    offset = 0
    while offset < len(data):
        try:
            offset += os.write(master_fd, data[offset:])
            continue
        except BlockingIOError:
            writable = loop.create_future()
            loop.add_writer(master_fd, _mark_ready, writable)
            try:
                await writable
            finally:
                loop.remove_writer(master_fd)


async def _send_output(websocket: WebSocket, master_fd: int) -> None:
    while True:
        try:
            data = await _read_pty(master_fd)
        except OSError:
            return
        if not data:
            return
        await websocket.send_text(
            json.dumps(
                {"type": "output", "data": data.decode("utf-8", errors="replace")},
                ensure_ascii=False,
            )
        )


async def _receive_input(websocket: WebSocket, master_fd: int) -> None:
    while True:
        raw = await websocket.receive_text()
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        message_type = message.get("type")
        if message_type == "input":
            data = message.get("data")
            if isinstance(data, str) and len(data) <= 16_384:
                await _write_pty(master_fd, data.encode("utf-8"))
        elif message_type == "resize":
            _resize_terminal(master_fd, message.get("rows"), message.get("cols"))


async def serve_terminal(websocket: WebSocket, home: Path) -> None:
    master_fd, child_pid = _start_shell(home)
    os.set_blocking(master_fd, False)
    _resize_terminal(master_fd, 28, 100)
    sender = asyncio.create_task(_send_output(websocket, master_fd))
    receiver = asyncio.create_task(_receive_input(websocket, master_fd))
    try:
        await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        sender.cancel()
        receiver.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        with suppress(OSError):
            os.close(master_fd)
        await asyncio.to_thread(_shutdown_terminal, child_pid)
