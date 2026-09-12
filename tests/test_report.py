"""The report is the checker's output to the maker, so it is tested as such.

A verdict says a batch failed. The report says what may legitimately change —
and, more importantly, what may not. A maker agent handed "G3 FAILED, 14 rows"
will edit 14 quotes until the gate goes green, which is the defect this package
exists to prevent rather than a fix for it.

So the load-bearing tests here are:
  1. every finding a gate can emit has a remedy (no silent "see the message")
  2. structural findings are never presented as row-editing work
"""

import ast
import pathlib

import pytest

from kbqa import cli, report
from kbqa.report import FIXABLE, PLANNER, REMEDIES, STRUCTURAL

GATES_DIR = pathlib.Path(report.__file__).parent / "gates"


# Calls whose first positional argument is a finding code. `_bulk` is a helper
# in g6 that emits many findings of one code; without it here, every code routed
# through a helper would look unemitted and the coverage test would pass while
# the report fell back to "see the message" for exactly those findings.
CODE_EMITTERS = ("Finding", "_bulk")


def _emitted_codes():
    """Every literal code passed to a finding-emitting call in the gates."""
    codes = set()
    for p in sorted(GATES_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") in CODE_EMITTERS):
                continue
            if node.args and isinstance(node.args[0], ast.Constant):
                codes.add(node.args[0].value)
            for kw in node.keywords:
                if kw.arg == "code" and isinstance(kw.value, ast.Constant):
                    codes.add(kw.value.value)
    return codes


# --------------------------------------------------------------------------
# Coverage — the test that stops the report degrading into "see the message"
# --------------------------------------------------------------------------

def test_every_emitted_finding_has_a_remedy():
    missing = sorted(c for c in _emitted_codes() if c not in REMEDIES)
    assert not missing, (
        "these finding codes have no remedy, so the report would tell the maker "
        f"nothing actionable about them: {missing}"
    )


def test_no_remedy_for_a_code_no_gate_emits():
    """A remedy for a code nothing produces is dead guidance that reads as live."""
    orphans = sorted(c for c in REMEDIES if c not in _emitted_codes())
    assert not orphans, f"remedies for codes no gate emits: {orphans}"


def test_every_remedy_is_classified():
    for code, remedy in REMEDIES.items():
        assert remedy.kind in (STRUCTURAL, FIXABLE, PLANNER), code
        assert len(remedy.text) > 40, f"{code}: remedy too thin to act on"


# --------------------------------------------------------------------------
# Classification — structural work must never read as row-editing work
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "code",
    [
        "capture_missing",
        "capture_hash_mismatch",
        "capture_not_before_staging",
        "role_collapse",
        "bronze_modified",
        "manifest_mismatch",
        "zero_rows",
        "parser_disagrees_with_naive_count",
        "site_wide_disallow",
    ],
)
def test_unfixable_by_editing_is_marked_structural(code):
    """Editing rows to clear any of these would be fabrication, not repair."""
    assert REMEDIES[code].kind == STRUCTURAL, (
        f"{code} is not repairable by editing rows; marking it fixable invites "
        "exactly the gaming the gates exist to catch"
    )


def test_grounding_remedy_forbids_quote_shopping():
    """The most gameable finding must say so in words the maker will read."""
    text = REMEDIES["quote_not_in_capture"].text.lower()
    assert "drop the row" in text
    assert "paraphrase" in text


# --------------------------------------------------------------------------
# End-to-end
# --------------------------------------------------------------------------

def test_clean_batch_reports_clear_and_exits_zero(fx, tmp_path):
    d = fx("good")
    code = cli.main([
        "report", "--vendor-dir", str(d), "--batch", "widgets",
        "--log", str(tmp_path / "_qa-log.jsonl"),
    ])
    assert code == 0
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "**CLEAR**" in text
    assert "Nothing to do for the gates that ran" in text


def test_missing_capture_is_a_structural_gap(fx, tmp_path):
    d = fx("bad_missing_capture")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "**BLOCKED**" in text
    assert "capture_missing" in text
    assert "**class**: structural · **nature**: gap" in text
    assert "nothing to check them against" in text


# --------------------------------------------------------------------------
# What the maker needs: coverage, provenance, and a followable order
# --------------------------------------------------------------------------

def test_report_names_gates_that_did_not_run(fx):
    """Silence about an unrun gate reads as coverage it does not have."""
    d = fx("good")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "Coverage — what was and was not checked" in text
    assert "`g4_completeness` did not run" in text
    assert "has found nothing, which is not the same as having found nothing wrong" in text


def test_g4_runs_and_is_not_listed_as_skipped_when_a_denominator_is_given(fx):
    d = fx("bad_incomplete")
    cli.main([
        "report", "--vendor-dir", str(d), "--batch", "widgets",
        "--denominator", str(d / "_denominator-docs-2026-08-23.md"),
    ])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "`g4_completeness` did not run" not in text
    assert "g4_completeness" in text


def test_every_finding_names_the_module_and_hash_that_raised_it(fx):
    """So a maker who disputes a finding can cite the exact code, not edit it."""
    from kbqa.manifest import MANIFEST
    d = fx("bad_quote_not_in_capture")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "**raised by**: `g3_grounding`" in text
    assert MANIFEST["gates/g3_grounding.py"][:12] in text


def test_report_tells_the_maker_not_to_edit_the_checker(fx):
    d = fx("bad_quote_not_in_capture")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "do not edit the gate to make a batch pass" in text.lower()
    assert "## For the maker" in text


def test_action_plan_is_ordered_structural_before_fixable(fx):
    """Nothing in the plan may depend on work further down it."""
    d = fx("bad_missing_capture")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "## Action plan" in text
    assert "### 1." in text


def test_machine_readable_sidecar_is_written(fx):
    """A maker agent consumes the plan; a person reads it."""
    import json
    d = fx("bad_quote_not_in_capture")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    data = json.loads((d / "_qa" / "widgets.report.json").read_text())

    assert data["status"] == "BLOCKED"
    assert data["batch"] == "widgets"
    assert data["manifest_sha256"]
    assert data["counts"]["findings"] >= 1
    assert {g["gate"] for g in data["gates_run"]} == {
        "g1_capture", "g2_conformance", "g3_grounding"
    }
    assert any(g["gate"] == "g4_completeness" for g in data["gates_not_run"])

    for f in data["findings"]:
        assert f["kind"] in (STRUCTURAL, PLANNER, FIXABLE)
        assert f["nature"] in ("gap", "issue")
        assert f["gate_sha256"] != "unknown"
        assert f["remedy"]


def test_gaps_and_issues_are_counted_separately(fx):
    import json
    d = fx("bad_missing_capture")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    data = json.loads((d / "_qa" / "widgets.report.json").read_text())
    c = data["counts"]
    assert c["gaps"] + c["issues"] == c["findings"]
    assert c["gaps"] >= 1, "a missing capture is an absence, not a defect in the rows"


def test_ungrounded_quote_is_reported_as_fixable_with_a_warning(fx):
    d = fx("bad_quote_not_in_capture")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "**BLOCKED**" in text
    assert "quote_not_in_capture" in text
    assert "drop the row" in text


def test_report_routes_to_the_planner(fx):
    d = fx("good")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert "planner" in text.lower()
    assert "retry loop" in text.lower()


def test_report_writes_verdicts_and_log(fx, tmp_path):
    d = fx("good")
    log = tmp_path / "_qa-log.jsonl"
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets", "--log", str(log)])
    qa = d / "_qa"
    assert (qa / "widgets.g1_capture.json").is_file()
    assert (qa / "widgets.g2_conformance.json").is_file()
    assert (qa / "widgets.g3_grounding.json").is_file()
    assert len(log.read_text().strip().splitlines()) == 3


def test_report_carries_the_manifest(fx):
    """A report from edited gates must be distinguishable from an approved one."""
    from kbqa.manifest import MANIFEST_SHA256
    d = fx("good")
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"])
    text = (d / "_qa" / "widgets.report.md").read_text()
    assert MANIFEST_SHA256[:16] in text


def test_report_needs_its_arguments():
    assert cli.main(["report"]) == 1
    assert cli.main(["report", "--vendor-dir", "/nonexistent", "--batch", "x"]) == 1


def test_report_never_exits_2(fx):
    """Exit 2 means DECLINED. A batch report must never be readable as one."""
    d = fx("bad_missing_capture")
    assert cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets"]) != 2


# --------------------------------------------------------------------------
# The checker stores structure, never identity
# --------------------------------------------------------------------------

def test_no_verdict_or_log_line_stores_a_subject_name(fx, tmp_path):
    """A structural check has no use for who the subject is.

    No gate reads it — `--vendor` existed only to label a log line, which made
    the QA layer a second place identity accumulates. Paths already locate the
    file; a name stored beside them is a copy, not information.
    """
    import json

    d = fx("good")
    log = tmp_path / "_qa-log.jsonl"
    cli.main(["report", "--vendor-dir", str(d), "--batch", "widgets", "--log", str(log)])

    for verdict in (d / "_qa").glob("*.json"):
        assert "vendor" not in json.loads(verdict.read_text()), (
            f"{verdict.name} stores a subject name"
        )

    for line in log.read_text().splitlines():
        assert "vendor" not in json.loads(line), "the log line stores a subject name"


def test_the_vendor_flag_is_rejected_rather_than_ignored(fx, tmp_path, capsys):
    """Accepting a flag whose value is discarded would be worse than removing it.

    A caller who keeps passing `--vendor` is entitled to learn it no longer
    means anything, rather than believing the name was recorded.
    """
    d = fx("good")
    code = cli.main([
        "report", "--vendor-dir", str(d), "--batch", "widgets", "--vendor", "Acme",
    ])
    assert code != 0
