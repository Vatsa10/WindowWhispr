"""Import every pure module.

Cheap insurance against two failure modes: a syntax/typo break in a module no
test happens to exercise yet, and drift between this list and the
``hiddenimports`` list in ``packaging/winwhispr.spec`` (a module missing there
vanishes silently from the frozen build).
"""

import importlib

import pytest

PURE_MODULES = [
    "core.audio_meter",
    "core.cleanup",
    "core.cleanup.gates",
    "core.cleanup.levels",
    "core.cleanup.normalize",
    "core.cleanup.orchestrator",
    "core.cleanup.prompts",
    "core.cleanup.provider_local",
    "core.commands",
    "core.dictionary",
    "core.dictionary.autolearn",
    "core.dictionary.similarity",
    "core.snippets",
    "core.stats",
    "core.diagnostics",
    "core.state",
    "core.state.actions",
    "core.state.events",
    "core.state.machine",
    "core.state.timing",
    "database.migrations",
]


@pytest.mark.parametrize("name", PURE_MODULES)
def test_imports(name):
    assert importlib.import_module(name) is not None
