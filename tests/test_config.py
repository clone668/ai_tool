from __future__ import annotations

import copy
from pathlib import Path

import pytest
from app.config import ConfigurationError, load_config, validate_config

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "projects.json"


def test_production_configuration_is_valid() -> None:
    config = load_config(CONFIG_PATH)

    assert config["host"]["address"] == "192.168.2.240"
    assert len(config["projects"]) == 13
    openclaw = next(project for project in config["projects"] if project["id"] == "openclaw")
    assert openclaw["components"][0]["type"] == "user_systemd"
    assert openclaw["components"][0]["user"] == "huxi"


def test_duplicate_project_ids_are_rejected() -> None:
    config = load_config(CONFIG_PATH)
    config["projects"].append(copy.deepcopy(config["projects"][0]))

    with pytest.raises(ConfigurationError, match="duplicate project"):
        validate_config(config)


def test_unknown_actions_are_rejected() -> None:
    config = load_config(CONFIG_PATH)
    config["projects"][0]["components"][0]["actions"] = ["delete"]

    with pytest.raises(ConfigurationError, match="invalid actions"):
        validate_config(config)


def test_compose_files_must_stay_under_data_disk() -> None:
    config = load_config(CONFIG_PATH)
    new_api = next(project for project in config["projects"] if project["id"] == "new-api")
    new_api["components"][0]["compose_file"] = "/tmp/docker-compose.yml"

    with pytest.raises(ConfigurationError, match="under /data"):
        validate_config(config)
