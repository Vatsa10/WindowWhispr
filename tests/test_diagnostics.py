from core.diagnostics import (
    MAX_HEADLINE_CHARS,
    Failure,
    all_diagnostics,
    diagnose,
)


def test_every_failure_has_copy():
    diags = all_diagnostics()
    assert len(diags) == len(Failure)
    for d in diags:
        assert d.headline.strip()
        assert d.detail.strip()


def test_headlines_fit_the_pill():
    for d in all_diagnostics():
        assert len(d.headline) <= MAX_HEADLINE_CHARS, d.headline


def test_wording_is_windows_only():
    # macOS phrasing leaking into Windows copy was a real WhimprFlow bug.
    banned = ("system settings", "system preferences", "accessibility", "keychain")
    for d in all_diagnostics():
        blob = f"{d.headline} {d.detail}".lower()
        for word in banned:
            assert word not in blob, (d.kind, word)


def test_deterministic():
    assert diagnose(Failure.MIC_BLOCKED) == diagnose(Failure.MIC_BLOCKED)
