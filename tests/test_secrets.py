import sys
import types

import pytest

from core import secrets


class FakeKeyring(types.ModuleType):
    def __init__(self, store=None, broken=False):
        super().__init__("keyring")
        self.store = store or {}
        self.broken = broken

    def get_password(self, service, name):
        if self.broken:
            raise RuntimeError("no backend")
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        if self.broken:
            raise RuntimeError("no backend")
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        if self.broken:
            raise RuntimeError("no backend")
        del self.store[(service, name)]


@pytest.fixture()
def fake_keyring(monkeypatch):
    module = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", module)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return module


def test_round_trip(fake_keyring):
    assert secrets.set_key("groq_api_key", "gsk_abc")
    assert secrets.get_key("groq_api_key") == "gsk_abc"
    assert secrets.has_key("groq_api_key")


def test_values_are_trimmed(fake_keyring):
    secrets.set_key("groq_api_key", "  gsk_abc \n")
    assert secrets.get_key("groq_api_key") == "gsk_abc"


def test_empty_value_clears_the_key(fake_keyring):
    secrets.set_key("groq_api_key", "gsk_abc")
    secrets.set_key("groq_api_key", "")
    assert secrets.get_key("groq_api_key") == ""
    assert not secrets.has_key("groq_api_key")


def test_clearing_an_absent_key_is_not_an_error(fake_keyring):
    assert secrets.set_key("groq_api_key", "")


def test_environment_fallback(fake_keyring, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from_env")
    assert secrets.get_key("groq_api_key") == "from_env"


def test_stored_key_wins_over_the_environment(fake_keyring, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from_env")
    secrets.set_key("groq_api_key", "from_store")
    assert secrets.get_key("groq_api_key") == "from_store"


def test_broken_backend_falls_back_instead_of_raising(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring(broken=True))
    monkeypatch.setenv("GROQ_API_KEY", "from_env")
    assert secrets.get_key("groq_api_key") == "from_env"
    assert secrets.set_key("groq_api_key", "x") is False


def test_unknown_name_has_no_env_fallback(fake_keyring):
    assert secrets.get_key("nonexistent_key") == ""
