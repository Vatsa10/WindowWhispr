"""The website's download links and the release's file names must agree.

Nothing connects these two files, so a rename on one side leaves the other
pointing at a 404 that nobody sees until somebody tries to download the app.
That already happened once. This is the check that would have caught it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "index.html"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def linked_assets() -> set[str]:
    """File names the site links at under releases/latest/download/."""
    html = PAGE.read_text(encoding="utf-8")
    return set(re.findall(r"/releases/latest/download/([^\"'\s]+)", html))


def published_assets() -> set[str]:
    """File names the release workflow uploads."""
    text = WORKFLOW.read_text(encoding="utf-8")
    files = re.search(r"files:\s*\|\n((?:\s+\S+\n)+)", text)
    assert files, "the release workflow no longer lists files to upload"
    return {line.strip() for line in files.group(1).splitlines() if line.strip()}


def test_every_link_on_the_site_is_something_the_release_publishes():
    missing = linked_assets() - published_assets()
    assert not missing, f"the site links to files no release produces: {sorted(missing)}"


def test_the_site_offers_both_the_installer_and_the_zip():
    names = linked_assets()
    assert any(n.endswith(".exe") for n in names), "no installer offered"
    assert any(n.endswith(".zip") for n in names), "no portable build offered"


def test_asset_names_carry_no_version():
    """A versioned name cannot be linked to permanently: releases/latest/
    download needs the exact file name, so the site would break every release.
    """
    for name in published_assets() | linked_assets():
        assert not re.search(r"\d+\.\d+\.\d+", name), (
            f"{name} has a version in it, so its download link dies next release")
