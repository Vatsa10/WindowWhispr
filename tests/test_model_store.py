"""Listing and deleting downloaded models.

``remove`` deletes directory trees, so most of what is tested here is the
refusal to delete the wrong thing.
"""

import pytest

from core import model_store, paths
from core.model_store import StoredModel


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A model directory laid out the way the app writes it."""
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(paths, "ov_cache_dir", lambda: tmp_path / "ov_cache")

    for kind, name, size in (
        ("whisper", "models--Systran--faster-whisper-base.en", 2048),
        ("whisper", "models--Systran--faster-distil-whisper-large-v3", 8192),
        ("llm", "OpenVINO_LFM2.5-350M-int8-ov", 4096),
    ):
        directory = tmp_path / "models" / kind / name
        directory.mkdir(parents=True)
        (directory / "model.bin").write_bytes(b"x" * size)
    (tmp_path / "ov_cache").mkdir()
    (tmp_path / "ov_cache" / "blob.cl_cache").write_bytes(b"y" * 1024)
    return tmp_path


def test_lists_everything_downloaded(store):
    names = [m.name for m in model_store.installed()]
    assert len(names) == 3
    assert any("faster-whisper-base.en" in n for n in names)
    assert any("LFM2.5" in n for n in names)


def test_shows_recognizable_model_names(store):
    # The cache spells them "models--Systran--faster-whisper-base.en"; someone
    # deciding what to delete should not have to decode that.
    names = [m.name for m in model_store.installed()]
    assert "Systran/faster-whisper-base.en" in names
    assert not any(n.startswith("models--") for n in names)


def test_ignores_cache_bookkeeping_directories(store):
    (store / "models" / "whisper" / ".locks").mkdir()
    names = [m.name for m in model_store.installed()]
    assert not any(n.startswith(".") for n in names)


def test_largest_first(store):
    sizes = [m.size_bytes for m in model_store.installed()]
    assert sizes == sorted(sizes, reverse=True)


def test_marks_the_configured_model_as_in_use(store):
    models = model_store.installed(active_models=("faster-whisper-base.en",))
    in_use = [m for m in models if m.in_use]
    assert len(in_use) == 1
    assert "base.en" in in_use[0].name


def test_reports_the_compile_cache_separately(store):
    cache = model_store.compile_cache()
    assert cache.size_bytes == 1024
    assert "Rebuilt" in cache.kind


def test_removes_a_model(store):
    model = next(m for m in model_store.installed() if "large-v3" in m.name)
    assert model_store.remove(model)
    assert not model.path.exists()
    assert len(model_store.installed()) == 2


def test_refuses_to_delete_outside_the_app_directory(store, tmp_path):
    elsewhere = tmp_path.parent / "not-ours"
    elsewhere.mkdir(exist_ok=True)
    (elsewhere / "precious.txt").write_text("do not delete")

    victim = StoredModel(name="evil", kind="?", path=elsewhere, size_bytes=1)
    assert model_store.remove(victim) is False
    assert (elsewhere / "precious.txt").exists()


def test_removing_something_absent_is_not_an_error(store):
    ghost = StoredModel(
        name="ghost", kind="?", path=store / "models" / "whisper" / "nope", size_bytes=0
    )
    assert model_store.remove(ghost) is False


def test_report_mentions_the_location_and_a_total(store):
    text = model_store.report()
    assert str(paths.models_dir()) in text
    assert "GB total" in text


def test_report_is_useful_when_nothing_is_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(paths, "ov_cache_dir", lambda: tmp_path / "ov_cache")
    assert "nothing downloaded yet" in model_store.report()
