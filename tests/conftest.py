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
def pinned_clock(monkeypatch):
    monkeypatch.setenv("KBQA_RUN_AT", "2026-08-23T18:40:11Z")
