import os
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Fixed mtimes. Git does not preserve mtime, so G1's ordering check needs the
# relationship established at test time rather than read off the disk.
BASE = 1_000_000_000
CAPTURE_MTIME = BASE
STAGING_MTIME = BASE + 100
LATE_CAPTURE_MTIME = BASE + 200


@pytest.fixture
def fx(tmp_path):
    """Copy a fixture into tmp_path and set mtimes deterministically."""

    def _mk(name: str, capture_after_staging: bool = False) -> Path:
        src = FIXTURES / name
        assert src.is_dir(), f"missing fixture {name}"
        dst = tmp_path / name
        shutil.copytree(src, dst)
        for p in dst.iterdir():
            if p.name.startswith("_capture-"):
                m = LATE_CAPTURE_MTIME if capture_after_staging else CAPTURE_MTIME
            elif p.name.startswith("_collect-"):
                m = STAGING_MTIME
            else:
                m = BASE
            os.utime(p, (m, m))
        return dst

    return _mk


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The suite never reaches the network. Since v6.18.0 `kbqa capture` and
    `kbqa index` run G0 themselves when today's robots record is missing, so a
    test that forgot to fake the web would otherwise fetch a real robots.txt.
    Tests that need a web install their own fake over these."""
    import urllib.error
    from kbqa import fetch
    from kbqa.gates import g0_permission

    def blocked(*a, **k):
        raise urllib.error.URLError("no network in the test suite")
    monkeypatch.setattr(fetch, "_open", blocked)
    monkeypatch.setattr(g0_permission, "_fetch", lambda host: (None, "no network in the test suite"))


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setenv("KBQA_RUN_AT", "2026-08-23T18:40:11Z")
