"""The checking skill pins a version and a manifest SHA. Keep them true.

The skill tells an agent to refuse a verdict when `--manifest` disagrees with
the pinned value. That check is the only signal an agent gets that the
validator was swapped — so a pin left stale across a release makes it fire on a
legitimate upgrade, and an agent that learns to ignore it has lost the signal
entirely.

The checks are written as functions over text so they can be proven to FAIL on
mutated input. A pin check that has never failed has not been tested.
"""

import json
import re
from pathlib import Path

import pytest

from kbqa import __version__
from kbqa.manifest import MANIFEST_SHA256

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "kbqa-check"
SKILL = SKILL_DIR / "SKILL.md"
SNIPPET = SKILL_DIR / "settings-snippet.json"

WRITING_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# Each closes one route to switching the checking off.
BYPASSES = [
    ("editing the installed validator", "site-packages/kbqa"),
    ("reinstalling it editable", "pip"),
    ("disabling the pre-push hook", ".git/hooks"),
    ("disabling CI", ".github/workflows"),
    ("bypassing the hook", "--no-verify"),
    ("rewriting the boundary itself", ".claude/settings.json"),
]


def pinned_versions(text: str):
    return re.findall(r"^(\d+\.\d+\.\d+)$", text, re.MULTILINE)


def pinned_manifests(text: str):
    return re.findall(r"manifest_sha256 ([0-9a-f]{64})", text)


def granted_tools(text: str):
    m = re.search(r"^allowed-tools:\s*(.+)$", text, re.MULTILINE)
    if not m:
        return None
    return {t.strip() for t in m.group(1).split(",")}


def uncovered_bypasses(deny: str):
    return [route for route, needle in BYPASSES if needle not in deny]


@pytest.fixture(scope="module")
def skill_text() -> str:
    assert SKILL.exists(), f"the checking skill is missing: {SKILL}"
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def deny_text() -> str:
    snippet = json.loads(SNIPPET.read_text(encoding="utf-8"))
    return " ".join(snippet["permissions"]["deny"])


# ── the shipped skill must be true ───────────────────────────────────────────

def test_pinned_version_matches_the_package(skill_text):
    pinned = pinned_versions(skill_text)
    assert pinned, "SKILL.md declares no expected version"
    assert __version__ in pinned, (
        f"SKILL.md pins {pinned} but this package is {__version__}. "
        "Update the pin in the same commit that tags the release."
    )


def test_pinned_manifest_matches_the_package(skill_text):
    pinned = pinned_manifests(skill_text)
    assert pinned, "SKILL.md declares no expected manifest_sha256"
    assert MANIFEST_SHA256 in pinned, (
        f"SKILL.md pins {pinned} but the manifest is {MANIFEST_SHA256}. "
        "Gate code changed without the pin being updated."
    )


def test_the_skill_cannot_write(skill_text):
    """No Edit, no Write. The boundary is the tool list, not the prose."""
    granted = granted_tools(skill_text)
    assert granted is not None, "SKILL.md declares no allowed-tools — it inherits every tool"
    assert not granted & WRITING_TOOLS, (
        f"the checking skill grants a writing tool: {sorted(granted)}. An agent "
        "that can edit the gate that is failing is the failure this package "
        "exists to catch."
    )


def test_the_deny_snippet_covers_every_bypass(deny_text):
    assert uncovered_bypasses(deny_text) == []


# ── and the checks must be capable of failing ────────────────────────────────

def test_a_stale_version_pin_is_caught(skill_text):
    mutated = skill_text.replace(__version__, "9.9.9")
    assert __version__ not in pinned_versions(mutated)


def test_a_stale_manifest_pin_is_caught(skill_text):
    mutated = re.sub(
        r"manifest_sha256 [0-9a-f]{64}", "manifest_sha256 " + "0" * 64, skill_text
    )
    assert MANIFEST_SHA256 not in pinned_manifests(mutated)


def test_a_skill_granted_write_is_caught(skill_text):
    mutated = re.sub(
        r"^(allowed-tools:.*)$", r"\1, Write", skill_text, count=1, flags=re.MULTILINE
    )
    assert granted_tools(mutated) & WRITING_TOOLS


def test_a_missing_tool_list_is_caught(skill_text):
    mutated = re.sub(r"^allowed-tools:.*$", "", skill_text, count=1, flags=re.MULTILINE)
    assert granted_tools(mutated) is None


def test_a_dropped_deny_rule_is_caught(deny_text):
    for _, needle in BYPASSES:
        mutated = " ".join(p for p in deny_text.split() if needle not in p)
        assert uncovered_bypasses(mutated), f"dropping {needle!r} went unnoticed"
