import json

import pytest

from core import config_store


@pytest.fixture()
def cfg_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(path))
    return path


def test_creates_defaults_when_missing(cfg_path):
    cfg = config_store.load_config()
    assert cfg["config_version"] == config_store.CONFIG_VERSION
    assert cfg_path.exists()


def test_backfills_new_keys_for_old_files(cfg_path):
    cfg_path.write_text(json.dumps({"hotkey": "ctrl+alt+d"}), encoding="utf-8")
    cfg = config_store.load_config()
    assert cfg["hotkey"] == "ctrl+alt+d"          # user value survives
    assert cfg["llm_device"] == "CPU"              # default backfilled
    assert cfg["config_version"] == config_store.CONFIG_VERSION


def test_migrate_is_idempotent(cfg_path):
    once = config_store.migrate({"config_version": 0})
    twice = config_store.migrate(dict(once))
    assert once == twice
    assert once["config_version"] == config_store.CONFIG_VERSION


def test_save_is_atomic(cfg_path):
    config_store.save_config({"hotkey": "x"})
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["hotkey"] == "x"
    assert not cfg_path.with_suffix(".json.tmp").exists()


def test_bad_json_falls_back_to_defaults(cfg_path):
    cfg_path.write_text("{not json", encoding="utf-8")
    cfg = config_store.load_config()
    assert cfg["hotkey"] == config_store.DEFAULT_CONFIG["hotkey"]
