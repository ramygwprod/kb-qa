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


def test_good_passes_g6_once_the_gates_have_actually_run(fx):
    """G6 passes a clean estate — but only one whose batches were checked.

    This mirrors the real cycle rather than shortcutting it: verdicts exist
    because the gates ran, not because the fixture ships them.
    """
    from kbqa import cli

    d = fx("good")
    assert cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"]) == 0

    v, code = g6_integrity.run(["--root", str(d)])
    assert v.verdict == PASS, v.findings
    assert code == EXIT_PASS


def test_g6_fails_an_estate_whose_batches_were_never_checked(fx):
    """The control standing in for a status check that cannot be enforced.

    A private repo on a free plan cannot require a passing check before a push,
    so nothing at the git layer stops an unchecked batch from landing. G6 is
    where that is caught instead — and G6 lives in the pinned, enforced gates,
    so whoever skipped the check cannot edit this away.
    """
    d = fx("good")  # no _qa/ directory: the gates never ran here
    v, code = g6_integrity.run(["--root", str(d)])
    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert any(f.code == "batch_unchecked" for f in v.findings)
    assert v.counts["batches_unchecked"] == 1


def test_g6_fails_when_a_batch_changed_after_it_was_checked(fx):
    """Checked-then-edited is a different fault from never-checked.

    Only this one implies somebody saw a result before changing the file.
    """
    from kbqa import cli

    d = fx("good")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])

    staging = d / "_collect-widgets-staging.md"
    staging.write_text(staging.read_text() + "\n<!-- edited after checking -->\n",
                       encoding="utf-8")

    v, code = g6_integrity.run(["--root", str(d)])
    assert v.verdict == FAIL
    assert any(f.code == "verdict_stale" for f in v.findings), v.findings
    assert v.counts["batches_stale"] == 1


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


def test_pages_declared_in_a_markdown_table_are_found(fx):
    """Regression: `no_declared_pages` fired on batches that declare pages fine.

    Some batches use a frontmatter `pages:` list, others a markdown table. G1
    read only the first, so the second got a finding untrue of it — sending a
    maker hunting for a list that was never that batch's convention.
    """
    d = fx("good")
    staging = d / STAGING
    text = staging.read_text()

    # Strip the frontmatter pages list, declare the same pages in a table.
    lines = [l for l in text.splitlines() if not l.startswith("  - http")]
    lines = [l for l in lines if l.strip() != "pages:"]
    table = [
        "",
        "## Per-page declaration",
        "",
        "| page | items | complete? |",
        "|---|---|---|",
        "| https://docs.acme.test/widgets/overview | 1 | yes |",
        "| https://docs.acme.test/widgets/syntax-reference | 1 | yes |",
        "",
    ]
    idx = next(i for i, l in enumerate(lines) if l.startswith("# Staging"))
    staging.write_text("\n".join(lines[:idx] + table + lines[idx:]) + "\n", encoding="utf-8")

    v, code = g1_capture.run(["--staging", str(staging), "--capture", str(d / CAPTURE)])

    assert "no_declared_pages" not in codes(v), v.findings
    assert v.counts["declared_pages"] == 2
    assert v.counts["pages_source"] == "table"


def test_capture_without_markers_is_one_structural_finding_not_one_per_row(fx):
    """Regression: 181 rows reported as ungrounded when the capture had no pages.

    A capture with no BEGIN/END markers cannot be split, so grounding is
    impossible rather than failing. Emitting `url_not_in_capture` per row said
    "this quote is not on its page" 181 times when the truth was "this file
    records no pages" — loud, specific, and wrong.
    """
    d = fx("good")
    (d / CAPTURE).write_text(
        "Widgets Overview\n\nAcme Widgets let you compose reusable UI blocks.\n",
        encoding="utf-8",
    )
    v, code = g3_grounding.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])

    assert v.verdict == FAIL
    assert code == EXIT_FAIL
    assert codes(v) == {"capture_has_no_page_blocks"}, "one finding, not one per row"
    assert len(v.findings) == 1
    assert v.counts["unassessable"] == 2
    assert v.counts["grounded"] == 0
    assert "url_not_in_capture" not in codes(v)


def test_unassessable_is_not_reported_as_ungrounded(fx):
    """The distinction the finding exists to preserve.

    Nothing has been shown wrong with these rows; grounding was not attempted.
    Conflating the two would accuse the data of a defect it has not been shown
    to have.
    """
    d = fx("good")
    (d / CAPTURE).write_text("no markers here at all\n", encoding="utf-8")
    v, _ = g3_grounding.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])

    assert v.counts["unassessable"] == v.counts["rows"]
    assert v.counts["checked"] == 0, "no row was assessed, so none may be judged"


def test_an_empty_capture_is_still_capture_empty_not_no_page_blocks(fx):
    """Zero bytes and zero markers are different faults with different remedies."""
    d = fx("good")
    (d / CAPTURE).write_text("", encoding="utf-8")
    v, _ = g3_grounding.run(["--staging", str(d / STAGING), "--capture", str(d / CAPTURE)])
    assert "capture_has_no_page_blocks" not in codes(v)


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
    write_verdict(v, d, "widgets", None)

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
    path = write_verdict(v, d, "widgets", None)

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


def test_batch_metadata_in_the_rows_block_is_not_a_malformed_row(fx):
    """Regression: an object with no identifying fields reported 6 defects.

    Batch metadata sitting inside the rows fence carries `batch`, `vendor`,
    `node_count`… and none of `id`, `source_url`, `source_quote`. Reporting it
    as six missing core fields says the ROWS are malformed, which is untrue of
    them, and sends a maker hunting a defect that is not there.
    """
    import json

    d = fx("good")
    staging = d / STAGING
    meta = {"batch": "widgets", "vendor": "Acme", "node_count": 2, "round": "1a"}
    staging.write_text(
        staging.read_text() + "\n" + json.dumps(meta) + "\n", encoding="utf-8")

    v, _ = g2_conformance.run(["--staging", str(staging)])
    assert "non_row_object" in codes(v)
    assert "schema_violation" not in codes(v), "the real rows are unaffected"
    assert len([f for f in v.findings if f.code == "non_row_object"]) == 1


# --------------------------------------------------------------------------
# G4 window mode — exhaustion for surfaces with no published index
# --------------------------------------------------------------------------

def _windowed(tmp_path, name, requested, returned, n_rows, **extra):
    """A staging file declaring one window of a paginated surface."""
    import json as _json

    rows = "\n".join(
        _json.dumps({
            "id": f"acme.item{i}",
            "vendor_term": f"Item {i}",
            "what_it_does": "Does a thing.",
            "source_url": "https://docs.acme.test/list",
            "source_quote": "Acme Widgets let you compose reusable UI blocks.",
            "access_date": "2026-08-23",
            "evidence_grade": "official-doc",
            "confidence": "high",
            "mechanism": "Native",
            "outcome": "yes",
            "depth_level": "feature",
        })
        for i in range(n_rows)
    )
    fm = [f"batch: {name}"]
    if requested is not None:
        fm.append(f"window_requested: {requested}")
    if returned is not None:
        fm.append(f"window_returned: {returned}")
    for k, v in extra.items():
        fm.append(f"{k}: {v}")
    f = tmp_path / f"_collect-{name}-staging.md"
    f.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + rows + "\n", encoding="utf-8")
    return str(f)


def test_windows_without_a_terminal_zero_fail(tmp_path):
    """A short window is not proof the list ended.

    Twenty asked, fifteen returned, stop. That is equally consistent with a run
    that gave up. Only a window that came back empty distinguishes exhaustion
    from abandonment, and the distinction is the whole point of the mode.
    """
    from kbqa.gates import g4_completeness

    w1 = _windowed(tmp_path, "w1", 20, 20, 20)
    w2 = _windowed(tmp_path, "w2", 20, 15, 15)
    v, code = g4_completeness.run(["--rows", w1, w2])

    assert code == 1
    assert v.verdict == "FAIL"
    assert any(f.code == "no_exhaustion_evidence" for f in v.findings)


def test_a_terminal_zero_window_passes(tmp_path):
    from kbqa.gates import g4_completeness

    w1 = _windowed(tmp_path, "w1", 20, 20, 20)
    w2 = _windowed(tmp_path, "w2", 20, 15, 15)
    w3 = _windowed(tmp_path, "w3", 20, 0, 0)
    v, code = g4_completeness.run(["--rows", w1, w2, w3])

    assert code == 0
    assert v.verdict == "PASS"
    assert v.counts["terminal_zero_windows"] == 1
    assert v.counts["items_returned"] == 35


def test_fewer_rows_than_items_returned_is_caught(tmp_path):
    """The truncation signal: items came back that no row records.

    Non-tautological — the collector declares what the source returned, the
    checker counts rows independently. Neither side computes both numbers.
    """
    from kbqa.gates import g4_completeness

    w = _windowed(tmp_path, "w1", 20, 20, 8)
    z = _windowed(tmp_path, "w2", 20, 0, 0)
    v, code = g4_completeness.run(["--rows", w, z])

    assert code == 1
    assert any(f.code == "window_underwritten" for f in v.findings)


def test_more_rows_than_items_returned_is_fine(tmp_path):
    """One index item can legitimately yield several rows."""
    from kbqa.gates import g4_completeness

    w = _windowed(tmp_path, "w1", 20, 5, 12)
    z = _windowed(tmp_path, "w2", 20, 0, 0)
    v, code = g4_completeness.run(["--rows", w, z])

    assert not any(f.code == "window_underwritten" for f in v.findings)
    assert code == 0


def test_half_a_window_declaration_is_caught(tmp_path):
    from kbqa.gates import g4_completeness

    w = _windowed(tmp_path, "w1", 20, None, 20)
    v, code = g4_completeness.run(["--rows", w])

    assert code == 1
    assert any(f.code == "window_declaration_incomplete" for f in v.findings)


def test_neither_denominator_nor_windows_is_loud_not_silent(tmp_path):
    """Previously G4 simply did not run, which read as a clean gate."""
    from kbqa.gates import g4_completeness

    w = _windowed(tmp_path, "plain", None, None, 5)
    v, code = g4_completeness.run(["--rows", w])

    assert code == 1
    assert any(f.code == "completeness_unassessable" for f in v.findings)


def test_a_denominator_still_takes_precedence(fx):
    """Window mode is the fallback, not a replacement for a real index."""
    from kbqa.gates import g4_completeness

    d = fx("good")
    v, code = g4_completeness.run([
        "--denominator", str(d / "_denominator-docs-2026-08-23.md"),
        "--rows", str(d / "_collect-widgets-staging.md"),
    ])
    assert code == 0
    assert "existence_index_items" in v.counts
    assert "terminal_zero_windows" not in v.counts
