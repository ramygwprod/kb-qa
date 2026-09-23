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

SKILLS = Path(__file__).resolve().parent.parent / "skills"
SKILL_DIR = SKILLS / "kbqa-check"
SKILL = SKILL_DIR / "SKILL.md"
SNIPPET = SKILL_DIR / "settings-snippet.json"

COLLECT = SKILLS / "kbqa-collect" / "SKILL.md"
COLLECT_SNIPPET = SKILLS / "kbqa-collect" / "settings-snippet.json"

# The collecting role is defined by what it cannot do. Granting any of these
# back would let one session fetch AND write, which is rows grounded in a
# context's memory of a page rather than in a capture.
COLLECT_FORBIDDEN = {"WebFetch", "Write", "Edit", "Bash", "NotebookEdit", "MultiEdit", "WebSearch"}

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
    """Match the WHOLE hex token, never a fixed count of it.

    The original pattern was `[0-9a-f]{64}`, which on a 65-character token
    matches the first 64 and reports a clean value. A hand-typed placeholder was
    65 characters long; every subsequent re-pin used the same pattern, replaced
    64 of the 65, and left the extra character in place. The pin was wrong for
    six releases and this test passed on every one of them, because the test and
    the re-pin shared the same blind spot.

    So: capture greedily, and let the caller judge the length.
    """
    return re.findall(r"manifest_sha256 ([0-9a-f]+)", text)


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


def test_the_pinned_manifest_is_a_wellformed_sha256(skill_text):
    """64 hex characters, exactly. Not 63, not 65.

    An agent comparing a real 64-character digest against a 65-character pin can
    never match it — so the check either halts every session or, once it stopped
    halting, reports a stale pin every single time. Either way the one signal
    that a validator was swapped becomes noise.
    """
    for value in pinned_manifests(skill_text):
        assert len(value) == 64, (
            f"pinned manifest is {len(value)} characters, not 64: {value!r}. "
            "No real digest can equal it."
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


# ── the collecting role ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def collect_text() -> str:
    assert COLLECT.exists(), f"the collecting skill is missing: {COLLECT}"
    return COLLECT.read_text(encoding="utf-8")


def test_the_collector_cannot_fetch_or_write(collect_text):
    """Delegation must be a fact about the tool list, not a request in prose.

    A session holding both WebFetch and Write will use both — under time
    pressure, in a long context, or simply because it is fewer steps. The rows
    are then grounded in that context's memory of a page rather than in a
    capture, and nothing downstream can tell the difference.
    """
    granted = granted_tools(collect_text)
    assert granted is not None, "kbqa-collect declares no allowed-tools"
    overreach = granted & COLLECT_FORBIDDEN
    assert not overreach, (
        f"kbqa-collect grants {sorted(overreach)}. It must be able to delegate "
        "and read, and nothing else."
    )


def test_the_collector_can_still_delegate(collect_text):
    """Restriction that leaves it unable to work is not safety, it is breakage."""
    granted = granted_tools(collect_text)
    assert granted & {"Task", "Agent"}, (
        "kbqa-collect cannot spawn a subagent, so it cannot collect at all"
    )


def test_the_collector_cannot_read_its_own_verdict():
    """A collecting context that sees its verdict will iterate against it."""
    import json

    deny = " ".join(json.loads(COLLECT_SNIPPET.read_text())["permissions"]["deny"])
    assert "Read(**/_qa/**)" in deny, "the maker can read the verdict on its own work"


def test_the_two_snippets_stay_mutually_exclusive():
    """The checking role MUST read _qa/. Denying it there would be silent breakage.

    Both snippets in one settings file is the mistake this guards: permission
    denies are session-wide, so a shared file cannot express both roles.
    """
    import json

    check = " ".join(json.loads(SNIPPET.read_text())["permissions"]["deny"])
    assert "_qa" not in check, (
        "the checking snippet denies reading _qa/, which is the checker's job"
    )


@pytest.mark.parametrize("tool", sorted(COLLECT_FORBIDDEN))
def test_a_collector_granted_a_forbidden_tool_is_caught(collect_text, tool):
    mutated = re.sub(
        r"^(allowed-tools:.*)$", r"\1, " + tool, collect_text, count=1, flags=re.MULTILINE
    )
    assert granted_tools(mutated) & COLLECT_FORBIDDEN


def test_both_snippets_carry_a_checkout_placeholder():
    """`**/kb-qa/**` only matches a directory literally named kb-qa.

    A working copy can be called anything. Without a path the operator
    substitutes, a session can edit the gates through the checkout while every
    other route to them is closed — the one hole that makes the rest decorative.
    """
    for snippet in (SNIPPET, COLLECT_SNIPPET):
        deny = " ".join(json.loads(snippet.read_text())["permissions"]["deny"])
        assert "CHECKOUT" in deny, (
            f"{snippet.parent.name} has no checkout placeholder, so a kb-qa "
            "working copy under any other name is writable"
        )


def test_a_malformed_pin_is_caught_at_any_length(skill_text):
    """The guard that was missing. Proven to fail in both directions."""
    real = MANIFEST_SHA256
    for bad in (real + "4", real[:-1], real + "abc"):
        mutated = re.sub(r"manifest_sha256 [0-9a-f]+", f"manifest_sha256 {bad}", skill_text)
        lengths = [len(v) for v in pinned_manifests(mutated)]
        assert 64 not in lengths, f"a {len(bad)}-character pin read as well-formed"


def test_the_old_pattern_would_have_missed_it():
    """Documents the blind spot, so it is not reintroduced as a tidy-up.

    `[0-9a-f]{64}` against a 65-character token yields a clean 64-character
    match and hides the defect. That is why this file now captures greedily.
    """
    malformed = f"manifest_sha256 {MANIFEST_SHA256}4"
    assert re.findall(r"manifest_sha256 ([0-9a-f]{64})", malformed) == [MANIFEST_SHA256]
    assert pinned_manifests(malformed) == [MANIFEST_SHA256 + "4"]
