from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .security import token_digest


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Session:
    token: str
    csrf_token: str
    username: str
    expires_at: str


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    csrf_token TEXT NOT NULL,
                    username TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    user_agent TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    project_id TEXT,
                    component_id TEXT,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    detail TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_audit_created_at
                    ON audit_log(created_at DESC);
                """
            )

    def create_session(
        self,
        username: str,
        ip_address: str,
        user_agent: str,
        hours: int,
    ) -> Session:
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        now = _utc_now()
        expires_at = now + timedelta(hours=hours)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    token_hash, csrf_token, username, created_at,
                    expires_at, ip_address, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_digest(token),
                    csrf_token,
                    username,
                    now.isoformat(),
                    expires_at.isoformat(),
                    ip_address,
                    user_agent[:300],
                ),
            )
        return Session(token, csrf_token, username, expires_at.isoformat())

    def get_session(self, token: str) -> dict[str, Any] | None:
        now = _utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            row = connection.execute(
                "SELECT * FROM sessions WHERE token_hash = ?", (token_digest(token),)
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))

    def record_audit(
        self,
        *,
        username: str,
        ip_address: str,
        action: str,
        outcome: str,
        detail: str,
        project_id: str | None = None,
        component_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (
                    created_at, username, ip_address, project_id,
                    component_id, action, outcome, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utc_now().isoformat(),
                    username,
                    ip_address,
                    project_id,
                    component_id,
                    action,
                    outcome,
                    detail[:2000],
                ),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [dict(row) for row in rows]
