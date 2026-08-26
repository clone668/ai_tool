from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


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


def _start_shell(home: Path) -> tuple[int, subprocess.Popen[bytes]]:
    if os.name == "nt":
        raise TerminalUnavailable("Web 终端仅在 Linux 部署环境中可用")

    import pty
    import pwd

    try:
        shell_user = pwd.getpwnam("ai-tool-shell")
        home_stat = home.stat()
    except (KeyError, OSError) as exc:
        raise TerminalUnavailable("低权限终端账户或目录不可用") from exc
    if not home.is_dir() or home_stat.st_uid != shell_user.pw_uid:
        raise TerminalUnavailable("低权限终端目录权限无效")
    master_fd, slave_fd = pty.openpty()
    environment = {"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "TERM": "xterm-256color"}
    try:
        process = subprocess.Popen(
            [
                "/usr/bin/sudo",
                "-n",
                "-H",
                "-u",
                "ai-tool-shell",
                "--",
                "/bin/bash",
                "--noprofile",
                "--norc",
            ],
            cwd=home,
            env=environment,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        os.close(master_fd)
        raise TerminalUnavailable("无法启动低权限终端") from exc
    finally:
        os.close(slave_fd)
    return master_fd, process


async def _send_output(websocket: WebSocket, master_fd: int) -> None:
    while True:
        try:
            data = await asyncio.to_thread(os.read, master_fd, 4096)
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
                await asyncio.to_thread(os.write, master_fd, data.encode("utf-8"))
        elif message_type == "resize":
            _resize_terminal(master_fd, message.get("rows"), message.get("cols"))


async def serve_terminal(websocket: WebSocket, home: Path) -> None:
    master_fd, process = _start_shell(home)
    _resize_terminal(master_fd, 28, 100)
    sender = asyncio.create_task(_send_output(websocket, master_fd))
    receiver = asyncio.create_task(_receive_input(websocket, master_fd))
    try:
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            with suppress(WebSocketDisconnect, asyncio.CancelledError, OSError):
                await task
    finally:
        sender.cancel()
        receiver.cancel()
        with suppress(OSError):
            os.close(master_fd)
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(process.wait, 2)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await asyncio.to_thread(process.wait)
