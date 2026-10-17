"""The v6.15.0 contract rules, each on a fixture that passes and one that fails.

These fixtures were written with the v6.15.0 handover (K1 row rules, K2
mandatory surfaces, K5 mapping files, K7 nothing checked) and lived beside it,
outside the repository, run by hand. Nothing in the suite exercised `surfaces`
or `mapcheck` codes, so a regression in either would have shipped green. They
are here now so every release runs them.

Each case asserts the same thing the handover's runner asserted.
"""

import shutil
from pathlib import Path

import pytest

from kbqa.gates import g2_conformance, g3_grounding, g6_integrity, mapcheck, surfaces

FX = Path(__file__).resolve().parent / "fixtures" / "contract"
B = "docs-2026-01-31"


@pytest.fixture
def fx(tmp_path):
    """A writable copy: gates may write beside their inputs."""
    dst = tmp_path / "contract"
    shutil.copytree(FX, dst)
    return dst


def codes(v):
    return {f.code for f in v.findings}


# ── K1 · row rules on current-convention batches ─────────────────────────────

def _g2(fx, sub):
    return g2_conformance.run(["--staging", str(fx / "K1" / sub / f"_collect-{B}-staging.md")])


def test_k1_a_new_batch_passes_with_the_rules_applied(fx):
    v, code = _g2(fx, "pass-new")
    assert code == 0, codes(v)
    assert v.counts["strict_rules"] == "applied"


def test_k1_an_array_written_one_object_per_line_passes(fx):
    v, code = _g2(fx, "pass-array-one-object-per-line")
    assert code == 0, codes(v)


@pytest.mark.parametrize("sub,want", [
    ("fail-rows-missed-by-parser", "parser_disagrees_with_naive_count"),
    ("fail-id-not-first", "id_not_first_key"),
    ("fail-parent-path-empty", "parent_path_empty"),
    ("fail-grade-spelling", "evidence_grade_spelling"),
    ("fail-source-not-http", "unfetchable_source"),
])
def test_k1_each_rule_fails_its_fixture(fx, sub, want):
    v, code = _g2(fx, sub)
    assert code == 1 and want in codes(v), sorted(codes(v))


def test_k1_a_url_with_no_begin_marker_is_not_grounded(fx):
    d = fx / "K1" / "fail-no-begin-marker"
    v, code = g3_grounding.run(["--staging", str(d / f"_collect-{B}-staging.md"),
                                "--capture", str(d / f"_capture-{B}.raw.txt")])
    assert code == 1 and "url_not_in_capture" in codes(v), sorted(codes(v))


def test_k1_rules_are_not_applied_to_a_legacy_name_and_it_says_so(fx):
    v, _ = g2_conformance.run(["--staging", str(
        fx / "K1" / "legacy-name-not-applied" / "_collect-reference-parents-staging.md")])
    assert not ({"id_not_first_key", "parent_path_empty", "evidence_grade_spelling"} & codes(v))
    assert v.counts["strict_rules"].startswith("not applied")


# ── K2 · the three mandatory surfaces ────────────────────────────────────────

def test_k2_a_denominator_or_a_stop_for_every_surface_passes(fx):
    v, code = surfaces.run(["--subject", str(fx / "K2" / "pass")])
    assert code == 0, sorted(codes(v))


def test_k2_a_missing_help_surface_fails(fx):
    v, code = surfaces.run(["--subject", str(fx / "K2" / "fail-help-missing")])
    assert code == 1 and "surface_missing" in codes(v), sorted(codes(v))


# ── K5 · the mapping files ───────────────────────────────────────────────────

def _mapcheck(fx, sub):
    d = fx / "K5" / sub
    return mapcheck.run(["--staging", str(d / f"_collect-{B}-staging.md"),
                         "--map", str(d / f"_map-{B}-A.jsonl"), "--map", str(d / f"_map-{B}-B.jsonl"),
                         "--codebook", str(fx / "ref" / "codebook.md"),
                         "--elements", str(fx / "ref" / "elements.jsonl"),
                         "--subject", str(d)])


def test_k5_two_valid_passes_agree_on_every_row(fx):
    v, code = _mapcheck(fx, "pass")
    assert code == 0, sorted(codes(v))
    assert v.counts["agreement"]["base_rows"] == 4
    assert v.counts["per_mapper"]["A"] == {**v.counts["per_mapper"]["A"], "needs_human": 1, "mapped": 3}


def test_k5_malformed_passes_fail_on_every_defect(fx):
    v, code = _mapcheck(fx, "fail-malformed")
    want = {"theme_unknown", "pcf_not_copied", "map_fields_mismatch", "map_id_missing"}
    assert code == 1 and want <= codes(v), sorted(codes(v))


def test_k5_one_element_on_most_rows_is_sent_to_a_human(fx):
    v, code = _mapcheck(fx, "fail-element-dominates")
    assert code == 1 and "element_dominates" in codes(v), sorted(codes(v))


# ── K7 · an empty check is not a pass ────────────────────────────────────────

def test_k7_an_empty_root_is_nothing_checked(fx):
    v, code = g6_integrity.run(["--root", str(fx / "K7" / "fail-empty-root")])
    assert code == 1 and "nothing_checked" in codes(v), sorted(codes(v))
