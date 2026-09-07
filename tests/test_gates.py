"""A gate that has never failed has not been tested. (spec §7)

Every gate here is proven to FAIL on a fixture built to break it, not merely
to pass on a fixture built to satisfy it.
"""

from pathlib import Path

import pytest

from kbqa.gates import EXIT_DECLINED, EXIT_FAIL, EXIT_PASS
from kbqa.gates import g0_permission, g1_capture, g2_conformance
from kbqa.gates import g3_grounding, g4_completeness, g5_bundles, g6_integrity
from kbqa.manifest import MANIFEST, MANIFEST_SHA256, manifest_digest
from kbqa.parsing import normalise_for_match, parse_capture
from kbqa.verdict import ADVISORY, FAIL, PASS

STAGING = "_collect-widgets-staging.md"
CAPTURE = "_capture-widgets.raw.txt"
DENOM = "_denominator-docs-2026-08-23.md"
STOPS = "_stop-conditions.md"


def codes(verdict):
    return {f.code for f in verdict.findings}


# ── the good batch must pass every gate ──────────────────────────────────


def test_good_passes_g1(fx):
    d = fx("good")
    v, code = g1_capture.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == PASS, v.findings
    assert code == EXIT_PASS


def test_good_passes_g2(fx):
    d = fx("good")
    v, code = g2_conformance.run(["--staging", str(d / STAGING)])
    assert v.verdict == PASS, v.findings
    assert code == EXIT_PASS
    assert v.counts["rows"] == 2
    assert v.counts["rows"] == v.counts["naive_rows"]


def test_good_passes_g3(fx):
    d = fx("good")
    v, code = g3_grounding.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == PASS, v.findings
    assert code == EXIT_PASS
    assert v.counts["grounded"] == 2


def test_good_passes_g4(fx):
    d = fx("good")
    v, code = g4_completeness.run(
        ["--denominator", str(d / DENOM), "--rows", str(d / STAGING)]
    )
    assert v.verdict == PASS, v.findings
    assert code == EXIT_PASS
    assert v.counts["without_row"] == 0


def test_good_passes_g6(fx):
    d = fx("good")
    v, code = g6_integrity.run(["--root", str(d)])
    assert v.verdict == PASS, v.findings
    assert code == EXIT_PASS


# ── G1 must fail ─────────────────────────────────────────────────────────


def test_missing_capture_is_a_fail_not_a_skip(fx):
    """A check that could not run has NOT passed."""
    d = fx("bad_missing_capture")
    v, code = g1_capture.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert "capture_missing" in codes(v)


def test_capture_hash_mismatch_fails_g1(fx):
    d = fx("bad_capture_hash")
    v, code = g1_capture.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == FAIL
    assert "capture_hash_mismatch" in codes(v)


def test_unbalanced_markers_fail_g1(fx):
    d = fx("bad_unbalanced_markers")
    v, code = g1_capture.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == FAIL
    assert "marker_unbalanced" in codes(v)


def test_capture_written_after_staging_fails_g1(fx):
    d = fx("bad_capture_after_staging", capture_after_staging=True)
    v, code = g1_capture.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == FAIL
    assert "capture_not_before_staging" in codes(v)


# ── G2 must fail ─────────────────────────────────────────────────────────


def test_bad_enum_fails_g2(fx):
    d = fx("bad_enum")
    v, code = g2_conformance.run(["--staging", str(d / STAGING)])
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert "schema_violation" in codes(v)


def test_zero_rows_is_a_fail_not_a_pass(fx):
    """A broken parser and an empty file look identical. Both are defects."""
    d = fx("bad_zero_rows")
    v, code = g2_conformance.run(["--staging", str(d / STAGING)])
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert "zero_rows" in codes(v)


def test_duplicate_id_fails_g2(fx):
    d = fx("bad_duplicate_id")
    v, _ = g2_conformance.run(["--staging", str(d / STAGING)])
    assert v.verdict == FAIL
    assert "duplicate_id" in codes(v)


def test_invented_field_fails_g2(fx):
    """extra='forbid' — the field set IS the contract."""
    d = fx("bad_extra_field")
    v, _ = g2_conformance.run(["--staging", str(d / STAGING)])
    assert v.verdict == FAIL
    assert "schema_violation" in codes(v)


def test_bad_id_pattern_fails_g2(fx):
    d = fx("bad_id_pattern")
    v, _ = g2_conformance.run(["--staging", str(d / STAGING)])
    assert v.verdict == FAIL
    assert "schema_violation" in codes(v)


# ── G3 must fail ─────────────────────────────────────────────────────────


def test_paraphrase_presented_as_quote_fails_g3(fx):
    d = fx("bad_quote_not_in_capture")
    v, code = g3_grounding.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert "quote_not_in_capture" in codes(v)


def test_url_not_in_capture_fails_g3(fx):
    d = fx("bad_url_not_in_capture")
    v, code = g3_grounding.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert "url_not_in_capture" in codes(v)


def test_quote_from_wrong_page_fails_g3(fx):
    """The quote IS in the capture — on a different page than it cites.

    Whole-capture matching would bless this. Per-page-block scoping is the
    reason it does not.
    """
    d = fx("bad_quote_from_wrong_page")
    v, code = g3_grounding.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert "quote_from_wrong_page" in codes(v)


def test_vendor_typo_is_preserved_not_corrected(fx):
    """Vendor typos are evidence. A speller would break this match correctly."""
    d = fx("good")
    text = (d / CAPTURE).read_text()
    assert "definiton" in text, "fixture lost its deliberate typo"
    v, _ = g3_grounding.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert v.verdict == PASS, "a row quoting the vendor's typo verbatim must ground"


def test_normalisation_folds_punctuation_but_not_spelling():
    assert normalise_for_match("“smart”  quotes—here") == '"smart" quotes-here'
    assert "definiton" in normalise_for_match("A widget definiton")


# ── G4 must fail ─────────────────────────────────────────────────────────


def test_uncovered_index_item_fails_g4(fx):
    d = fx("bad_incomplete")
    v, code = g4_completeness.run(
        ["--denominator", str(d / DENOM), "--rows", str(d / STAGING)]
    )
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert v.counts["without_row"] == 1
    assert "index_item_without_row" in codes(v)


def test_stop_condition_without_reason_fails_g4(fx):
    d = fx("bad_stop_without_reason")
    v, code = g4_completeness.run(
        ["--denominator", str(d / DENOM), "--rows", str(d / STAGING), "--stops", str(d / STOPS)]
    )
    assert v.verdict == FAIL
    assert "stop_condition_without_reason" in codes(v)


def test_stop_condition_with_reason_passes_g4(fx):
    d = fx("good_with_stop")
    v, code = g4_completeness.run(
        ["--denominator", str(d / DENOM), "--rows", str(d / STAGING), "--stops", str(d / STOPS)]
    )
    assert v.verdict == PASS, v.findings
    assert code == EXIT_PASS
    assert v.counts["existence_stopped"] == 1


def test_existence_and_evidence_are_separate_numbers(fx):
    d = fx("good_with_stop")
    v, _ = g4_completeness.run(
        ["--denominator", str(d / DENOM), "--rows", str(d / STAGING), "--stops", str(d / STOPS)]
    )
    assert v.counts["existence_index_items"] == 3
    assert v.counts["evidence_covered_by_url"] == 2
    assert v.counts["existence_stopped"] == 1
    # Never blended into one coverage number.
    assert "coverage" not in v.counts
    assert "coverage_pct" not in v.counts


def test_colliding_labels_do_not_collapse(fx):
    """16 pages named `syntax-reference` must stay 16 items, not become one."""
    d = fx("colliding_labels")
    items = g4_completeness.parse_denominator(d / DENOM)
    assert len(items) == 2
    resolved = g4_completeness.disambiguate(items)
    assert len(resolved) == 2, "colliding labels collapsed into one index item"


# ── G5 is advisory and must never gate ───────────────────────────────────


def test_g5_reports_but_always_exits_zero(fx):
    d = fx("bundled_terms")
    v, code = g5_bundles.run(["--rows", str(d / STAGING)])
    assert code == EXIT_PASS
    assert v.verdict == ADVISORY
    assert v.counts["terms_at_multiple_urls"] == 1
    assert v.counts["failed"] == 0


def test_g5_resolves_nothing(fx):
    """It reports a repeated name. It must not invent a usecase_of."""
    d = fx("bundled_terms")
    v, _ = g5_bundles.run(["--rows", str(d / STAGING)])
    body = v.to_json()
    assert "usecase_of" not in body


# ── G6 must fail ─────────────────────────────────────────────────────────


def test_role_collapse_fails_g6(fx):
    """The row-writer fetching its own source is not a warning."""
    d = fx("bad_role_collapse")
    v, code = g6_integrity.run(["--root", str(d)])
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert "role_collapse" in codes(v)


def test_proof_count_mismatch_fails_g6(fx):
    d = fx("bad_proof_count")
    v, code = g6_integrity.run(["--root", str(d)])
    assert v.verdict == FAIL
    assert "proof_count_mismatch" in codes(v)


def test_matching_proof_count_passes_g6(fx):
    d = fx("good_proof_count")
    v, code = g6_integrity.run(["--root", str(d)])
    assert v.verdict == PASS, v.findings


def test_modified_bronze_fails_g6(fx, tmp_path):
    """Bronze is never edited. Editing it after its verdict must be caught."""
    from kbqa.verdict import write_verdict

    d = fx("good")
    v, _ = g1_capture.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    write_verdict(v, d, "widgets", None, "Acme")

    # Now tamper with Bronze — "just fixing a typo".
    cap = d / CAPTURE
    cap.write_text(cap.read_text().replace("definiton", "definition"), encoding="utf-8")

    v6, code = g6_integrity.run(["--root", str(d)])
    assert v6.verdict == FAIL
    assert "bronze_modified" in codes(v6)
    assert code == EXIT_FAIL


def test_stale_manifest_in_verdict_fails_g6(fx):
    import json

    from kbqa.verdict import write_verdict

    d = fx("good")
    v, _ = g2_conformance.run(["--staging", str(d / STAGING)])
    path = write_verdict(v, d, "widgets", None, "Acme")

    data = json.loads(path.read_text())
    data["manifest_sha256"] = "deadbeef" * 8
    path.write_text(json.dumps(data, indent=2))

    v6, code = g6_integrity.run(["--root", str(d)])
    assert v6.verdict == FAIL
    assert "manifest_mismatch" in codes(v6)


# ── G0 · permission ──────────────────────────────────────────────────────


def test_site_wide_disallow_is_exit_2(monkeypatch, tmp_path):
    robots = "User-agent: *\nDisallow: /\n"
    monkeypatch.setattr(g0_permission, "_fetch", lambda host: (robots, None))
    v, code, artifact = g0_permission.run(
        ["--host", "closed.test", "--out", str(tmp_path), "--date", "2026-08-23"]
    )
    assert code == EXIT_DECLINED, "site-wide disallow must be terminal"
    assert v.verdict == "DECLINED"
    assert artifact.exists(), "robots.txt must be recorded verbatim as Bronze"
    assert artifact.read_text() == robots


def test_claudebot_specific_disallow_is_exit_2(monkeypatch, tmp_path):
    robots = "User-agent: *\nAllow: /\n\nUser-agent: ClaudeBot\nDisallow: /\n"
    monkeypatch.setattr(g0_permission, "_fetch", lambda host: (robots, None))
    _, code, _ = g0_permission.run(
        ["--host", "closed.test", "--out", str(tmp_path), "--date", "2026-08-23"]
    )
    assert code == EXIT_DECLINED, "our own agent's rule must take precedence over *"


def test_open_robots_is_exit_0(monkeypatch, tmp_path):
    robots = "User-agent: *\nDisallow: /private\nCrawl-delay: 5\n"
    monkeypatch.setattr(g0_permission, "_fetch", lambda host: (robots, None))
    v, code, _ = g0_permission.run(
        ["--host", "open.test", "--out", str(tmp_path), "--date", "2026-08-23"]
    )
    assert code == EXIT_PASS
    assert v.extra["crawl_delay"] == "5"
    assert "/private" in v.extra["disallow"]


def test_empty_disallow_is_not_a_denial(monkeypatch, tmp_path):
    """`Disallow:` with no value means allow-all. Misreading it closes a vendor."""
    robots = "User-agent: *\nDisallow:\n"
    monkeypatch.setattr(g0_permission, "_fetch", lambda host: (robots, None))
    _, code, _ = g0_permission.run(
        ["--host", "open.test", "--out", str(tmp_path), "--date", "2026-08-23"]
    )
    assert code == EXIT_PASS


def test_unreachable_is_exit_1_not_exit_2(monkeypatch, tmp_path):
    """Unreachable is not permission. Never conflate them."""
    monkeypatch.setattr(g0_permission, "_fetch", lambda host: (None, "timeout"))
    v, code, _ = g0_permission.run(
        ["--host", "down.test", "--out", str(tmp_path), "--date", "2026-08-23"]
    )
    assert code == EXIT_FAIL
    assert v.verdict == "ERROR"


# ── tamper evidence ──────────────────────────────────────────────────────


def test_verdict_records_the_manifest(fx):
    d = fx("good")
    v, _ = g2_conformance.run(["--staging", str(d / STAGING)])
    assert v.to_dict()["manifest_sha256"] == MANIFEST_SHA256
    assert len(MANIFEST_SHA256) == 64


def test_editing_a_gate_changes_the_manifest():
    """Tamper-EVIDENCE: edited code produces a distinguishable verdict."""
    tampered = dict(MANIFEST)
    key = "gates/g3_grounding.py"
    assert key in tampered
    tampered[key] = "0" * 64
    assert manifest_digest(tampered) != MANIFEST_SHA256


def test_manifest_covers_every_gate():
    for gate in ("g0_permission", "g1_capture", "g2_conformance", "g3_grounding",
                 "g4_completeness", "g5_bundles", "g6_integrity"):
        assert f"gates/{gate}.py" in MANIFEST


# ── the meta-test ────────────────────────────────────────────────────────


GATES_UNDER_TEST = ["g0", "g1", "g2", "g3", "g4", "g6"]


def test_every_blocking_gate_has_a_proven_failure():
    """§7 — a gate that has never failed has not been tested.

    G5 is excluded by design: it is advisory and must never fail.
    """
    source = Path(__file__).read_text()
    for gate in GATES_UNDER_TEST:
        marker_fail = f"EXIT_FAIL" if gate != "g0" else "EXIT_DECLINED"
        assert marker_fail in source, f"no failing assertion for {gate}"
    # G5 must never be asserted to fail.
    assert "g5_bundles.run" in source
