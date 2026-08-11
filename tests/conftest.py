from __future__ import annotations

from pathlib import Path

import pytest
from app.config import ROOT_DIR, Settings


@pytest.fixture
def demo_settings(tmp_path: Path) -> Settings:
    return Settings(
        config_path=ROOT_DIR / "config" / "projects.json",
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "static",
        ops_helper=tmp_path / "missing-helper",
        demo=True,
        cookie_secure=False,
        session_hours=12,
        password_hash=None,
        demo_password="dev-password",
    )
