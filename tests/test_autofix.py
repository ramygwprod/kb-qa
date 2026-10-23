"""v6.22.0 — `kbqa autofix`: the mechanical findings, fixed by code before the fix round.

A window is captured and staged by code (as in `test_stage.py`), a row is then
spoiled the way a hand edit spoils it, `kbqa report` checks the batch, and
autofix reads that report. It fixes only what has one right answer computed
from the evidence — a known respelling of a grade, the breadcrumb and its depth
from the receipt, `id` first — records every change, keeps the old bytes, and
leaves everything else, with its reason, for the row-writer.
"""

import contextlib
import hashlib
import io
import json
from pathlib import Path

import pytest

from kbqa import autofix, cli, report
from kbqa.parsing import parse_staging
from test_stage import GOOD, P1, P2, _drafts, _run, window  # noqa: F401  (window is a fixture)

CRUMB = "Docs > Webhooks > Retries"


def _staged(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD)
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0, out
    return d, b, Path(out["staging"])


def _edit(stg: Path, *changes):
    """Rewrite row lines: each change is (row index, function of the row) and
    the function returns the new row, or a string to write as the line."""
    lines = stg.read_text(encoding="utf-8").split("\n")
    at = [i for i, ln in enumerate(lines) if ln.startswith("{")]
    for idx, fn in changes:
        new = fn(json.loads(lines[at[idx]]))
        lines[at[idx]] = new if isinstance(new, str) else json.dumps(new, ensure_ascii=False)
    stg.write_text("\n".join(lines), encoding="utf-8")


def _set(**kv):
    return lambda o: {**o, **kv}


def _check(d, b):
    with contextlib.redirect_stdout(io.StringIO()):
        report.run(["--vendor-dir", str(d), "--batch", b])
    return json.loads((d / "_qa" / f"{b}.report.json").read_text())


def _fix(d, b):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = autofix.run(["--subject", str(d), "--batch", b])
    return code, json.loads(out.getvalue())


def _rows(stg):
    return [rp.obj for rp in parse_staging(stg).rows]


def _qa_files(d, b):
    return sorted(p.name for p in (d / "_qa").iterdir() if ".autofix-" in p.name or "before-autofix" in p.name)


def _codes(rep):
    return sorted(f["code"] for f in rep["findings"])


# ── fixed by code, recorded, the old bytes kept ──────────────────────────────

def test_known_respellings_are_fixed_and_every_change_recorded(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="Official-Doc")), (1, _set(evidence_grade="verify")),
          (2, _set(evidence_grade=" [ Verify ] ")))
    before = stg.read_bytes()
    rep = _check(d, b)
    assert _codes(rep).count("evidence_grade_spelling") == 3
    code, out = _fix(d, b)
    assert code == 0, out
    assert out["fixed"] == {"evidence_grade_spelling": 3}
    assert [r["evidence_grade"] for r in _rows(stg)] == ["official-doc", "[verify]", "[verify]"]
    assert [(c["code"], c["field"], c["before"], c["after"]) for c in out["changes"]] == [
        ("evidence_grade_spelling", "evidence_grade", "Official-Doc", "official-doc"),
        ("evidence_grade_spelling", "evidence_grade", "verify", "[verify]"),
        ("evidence_grade_spelling", "evidence_grade", " [ Verify ] ", "[verify]")]
    assert [c["id"] for c in out["changes"]] == [r["id"] for r in _rows(stg)]
    # the schema findings on those grades are resolved by the fix, checked against the row model
    assert {f["code"] for f in out["resolved_by_a_fix"]} == {"schema_violation"}
    assert out["left_for_row_writer"] == {} and "kbqa-check" in out["next_step"]
    qa = d / "_qa"
    assert (qa / f"{b}.staging-before-autofix-1.md").read_bytes() == before
    record = json.loads((qa / f"{b}.autofix-1.json").read_text())
    assert record["changes"] == out["changes"]
    assert record["staging_sha256_before"] == hashlib.sha256(before).hexdigest() == rep["staging_sha256"]
    assert record["staging_sha256_after"] == hashlib.sha256(stg.read_bytes()).hexdigest()
    assert out["files_written"] == [str(qa / f"{b}.staging-before-autofix-1.md"), str(qa / f"{b}.autofix-1.json"),
                                    str(stg)]
    again = _check(d, b)
    assert again["status"] == "CLEAR", _codes(again)


def test_only_the_fixed_fields_change(window):
    d, b, stg = _staged(window)
    _edit(stg, (1, _set(evidence_grade="Help")))
    old = stg.read_text().split("\n")
    _check(d, b)
    _fix(d, b)
    new = stg.read_text().split("\n")
    assert len(new) == len(old)
    differ = [i for i, (x, y) in enumerate(zip(old, new)) if x != y]
    assert len(differ) == 1
    a, z = json.loads(old[differ[0]]), json.loads(new[differ[0]])
    assert list(a) == list(z) and {k for k in a if a[k] != z[k]} == {"evidence_grade"}


def test_a_grade_that_is_no_known_respelling_is_left_and_nothing_is_written(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="official doc")), (1, _set(evidence_grade="excellent")))
    before = stg.read_bytes()
    _check(d, b)
    code, out = _fix(d, b)
    assert code == 0 and out["fixed"] == {} and out["changes"] == [] and out["files_written"] == []
    assert out["left_for_row_writer"]["evidence_grade_spelling"] == 2
    assert all("no known respelling" in f["why_not_by_code"] for f in out["left_findings"]
               if f["code"] == "evidence_grade_spelling")
    assert stg.read_bytes() == before and _qa_files(d, b) == []
    assert "row-writer" in out["next_step"] and "Not /kbqa-check before" not in out["next_step"]


def test_parent_path_and_depth_are_derived_from_the_receipt_as_stage_does(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(parent_path="", depth_level="unknown")), (1, _set(depth_level="unknown")),
          (2, _set(parent_path="")))
    _check(d, b)
    code, out = _fix(d, b)
    assert code == 0, out
    assert out["fixed"] == {"depth_unknown_with_breadcrumb": 1, "parent_path_empty": 2}
    rows = _rows(stg)
    assert (rows[0]["parent_path"], rows[0]["depth_level"]) == (CRUMB, "3")
    assert (rows[1]["parent_path"], rows[1]["depth_level"]) == (CRUMB, "3")
    assert (rows[2]["parent_path"], rows[2]["depth_level"]) == ("unknown", "unknown")  # a page with no breadcrumb
    assert [(c["code"], c["line"] - out["changes"][0]["line"], c["field"], c["before"], c["after"])
            for c in out["changes"]] == [
        ("parent_path_empty", 0, "parent_path", "", CRUMB),
        ("parent_path_empty", 0, "depth_level", "unknown", "3"),
        ("depth_unknown_with_breadcrumb", 1, "depth_level", "unknown", "3"),
        ("parent_path_empty", 2, "parent_path", "", "unknown")]
    assert _check(d, b)["status"] == "CLEAR"


def test_a_depth_is_left_when_parent_path_is_not_its_parts_breadcrumb(window):
    d, b, stg = _staged(window)
    _edit(stg, (1, _set(parent_path="Docs > Retries", depth_level="unknown")))
    _check(d, b)
    _, out = _fix(d, b)
    assert out["changes"] == [] and out["left_for_row_writer"] == {"depth_unknown_with_breadcrumb": 1}
    assert "not the breadcrumb of its part" in out["left_findings"][0]["why_not_by_code"]


def test_a_page_the_receipt_does_not_have_gives_no_breadcrumb(window):
    d, b, stg = _staged(window)
    _edit(stg, (1, _set(parent_path="", source_url=f"{P1}-moved")))
    _check(d, b)
    _, out = _fix(d, b)
    assert out["changes"] == []
    why = [f["why_not_by_code"] for f in out["left_findings"] if f["code"] == "parent_path_empty"]
    assert why and "is not a page of the batch's receipt" in why[0]


def test_without_a_receipt_that_vouches_for_the_staging_file_nothing_is_derived(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(parent_path="")))
    receipt = d / "_raw" / b / "RECEIPT.json"
    receipt.rename(receipt.with_suffix(".moved"))
    _check(d, b)
    _, out = _fix(d, b)
    assert out["changes"] == [] and "cannot vouch" in out["left_findings"][0]["why_not_by_code"]


def test_a_staging_file_naming_another_capture_gets_nothing_from_the_receipt(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(parent_path="")))
    stg.write_text(stg.read_text().replace("source_capture_sha256: ", "source_capture_sha256: 00"))
    rep = _check(d, b)
    _, out = _fix(d, b)
    assert out["changes"] == []
    assert "is not this staging file's evidence" in out["left_findings"][0]["why_not_by_code"]
    # a structural finding never goes to the row-writer
    assert "capture_hash_mismatch" in _codes(rep)
    assert out["not_for_row_writer"].get("capture_hash_mismatch") == 1
    assert "capture_hash_mismatch" not in out["left_for_row_writer"]


def _parts(d, b, fn):
    path = d / "_raw" / b / "RECEIPT.json"
    rec = json.loads(path.read_text())
    page = next(p for p in rec["pages"] if p["url"] == P1)
    page["parts"] = fn(page["parts"])
    path.write_text(json.dumps(rec))


def test_parts_that_give_different_breadcrumbs_are_left(window):
    d, b, stg = _staged(window)
    _parts(d, b, lambda parts: parts + [{**parts[0], "breadcrumb": "Docs > Elsewhere"}])
    _edit(stg, (0, _set(parent_path="")))
    _check(d, b)
    _, out = _fix(d, b)
    assert out["changes"] == [] and "2 different breadcrumbs" in out["left_findings"][0]["why_not_by_code"]


def test_parts_without_a_breadcrumb_field_are_left(window):
    d, b, stg = _staged(window)
    _parts(d, b, lambda parts: [{k: v for k, v in p.items() if k != "breadcrumb"} for p in parts])
    _edit(stg, (0, _set(parent_path="")))
    _check(d, b)
    _, out = _fix(d, b)
    assert out["changes"] == [] and "carry no breadcrumb" in out["left_findings"][0]["why_not_by_code"]


def test_id_is_moved_first_and_no_value_changes(window):
    d, b, stg = _staged(window)
    _edit(stg, (2, lambda o: {**{k: v for k, v in o.items() if k != "id"}, "id": o["id"]}))
    old = _rows(stg)[2]
    _check(d, b)
    _, out = _fix(d, b)
    assert out["fixed"] == {"id_not_first_key": 1}
    new = _rows(stg)[2]
    assert new == old and list(new)[0] == "id" and list(new)[1:] == [k for k in old if k != "id"]
    c = out["changes"][0]
    assert (c["field"], c["before"], c["after"]) == ("key order", list(old), list(new))


def test_a_line_not_written_as_stage_writes_it_is_left(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, lambda o: json.dumps({**o, "evidence_grade": "verify"}, ensure_ascii=False,
                                        separators=(",", ":"))))
    before = stg.read_bytes()
    _check(d, b)
    _, out = _fix(d, b)
    assert out["changes"] == [] and stg.read_bytes() == before
    assert "not as kbqa stage writes it" in out["left_findings"][0]["why_not_by_code"]


def test_other_findings_are_left_for_the_row_writer_word_for_word(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="Help", confidence="HIGH")), (1, _set(interface_type="api")))
    rep = _check(d, b)
    _, out = _fix(d, b)
    assert out["fixed"] == {"evidence_grade_spelling": 1}
    assert out["left_for_row_writer"] == {"interface_type_unknown": 1, "schema_violation": 1}
    for f in out["left_findings"]:
        assert any(f["where"] == g["where"] and f["message"] == g["message"] for g in rep["findings"])
    # the confidence finding is on a fixed row, but its field still fails
    assert [f["message"].split(":")[0] for f in out["left_findings"] if f["code"] == "schema_violation"] == \
        ["confidence"]
    assert "row-writer" in out["next_step"] and "Not /kbqa-check before" in out["next_step"]


def test_a_finding_the_row_does_not_have_changes_nothing(window):
    """A report is code's output, but autofix still checks each finding against
    the row before it changes anything."""
    d, b, stg = _staged(window)
    _edit(stg, (2, lambda o: {k: v for k, v in o.items() if k != "id"}))
    rep = _check(d, b)
    w = [f"{stg.name}:{rp.line_no}" for rp in parse_staging(stg).rows]
    rep["findings"] = [
        {"code": "evidence_grade_spelling", "kind": "fixable", "where": w[0], "message": "forged"},
        {"code": "id_not_first_key", "kind": "fixable", "where": w[0], "message": "forged"},
        {"code": "parent_path_empty", "kind": "fixable", "where": w[0], "message": "forged"},
        {"code": "depth_unknown_with_breadcrumb", "kind": "fixable", "where": w[0], "message": "forged"},
        {"code": "id_not_first_key", "kind": "fixable", "where": w[2], "message": "forged"},
        {"code": "id_not_first_key", "kind": "fixable", "where": "elsewhere.md:4", "message": "forged"}]
    (d / "_qa" / f"{b}.report.json").write_text(json.dumps(rep))
    before = stg.read_bytes()
    code, out = _fix(d, b)
    assert code == 0 and out["changes"] == [] and stg.read_bytes() == before and _qa_files(d, b) == []
    assert [f["why_not_by_code"] for f in out["left_findings"]] == [
        "evidence_grade is already the schema's spelling", "id is already the first key",
        "parent_path is not empty", "depth_level is not unknown", "the row has no id",
        "'elsewhere.md:4' names no row of " + stg.name]


# ── refused: the report must be on these bytes ───────────────────────────────

def test_refused_without_a_report(window):
    d, b, stg = _staged(window)
    code, out = _fix(d, b)
    assert code == 1 and "no check report" in out["refused"]


def test_refused_when_the_report_is_not_on_the_current_bytes(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="verify")))
    _check(d, b)
    _edit(stg, (1, _set(evidence_grade="verify")))
    before = stg.read_bytes()
    code, out = _fix(d, b)
    assert code == 1 and "is not the report of these rows" in out["refused"]
    assert stg.read_bytes() == before and _qa_files(d, b) == []


def _check_logged(d, b, log=True):
    args = ["--vendor-dir", str(d), "--batch", b] + (["--log", str(d / "_qa-log.jsonl")] if log else [])
    with contextlib.redirect_stdout(io.StringIO()):
        report.run(args)
    return json.loads((d / "_qa" / f"{b}.report.json").read_text())


def test_round_one_is_fixed(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="verify")))
    assert _check_logged(d, b)["round"] == 1
    code, out = _fix(d, b)
    assert code == 0 and out["fixed"] == {"evidence_grade_spelling": 1}


@pytest.mark.parametrize("logged", [True, False], ids=["round-in-report", "round-from-the-log"])
def test_a_report_of_round_two_is_refused_the_batch_is_the_operators(window, logged):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="verify")))
    _check_logged(d, b)                       # round 1, recorded in the subject's log
    _edit(stg, (1, _set(evidence_grade="verify")))
    rep = _check_logged(d, b, log=logged)     # these bytes are round 2
    assert rep["round"] == (2 if logged else None)
    before = stg.read_bytes()
    code, out = _fix(d, b)
    assert code == 1 and "round 2" in out["refused"]
    assert out["next_step"] == "operator: the one fix round is used; the batch is PARKED for the operator"
    assert stg.read_bytes() == before and _qa_files(d, b) == []


def test_a_legacy_batch_is_never_edited(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="verify")))
    rep = _check(d, b)
    legacy = "legacy-batch"
    lstg = d / f"_collect-{legacy}-staging.md"
    lstg.write_bytes(stg.read_bytes())
    (d / "_qa" / f"{legacy}.report.json").write_text(json.dumps(
        {**rep, "batch": legacy, "findings": [{**f, "where": f["where"].replace(stg.name, lstg.name)}
                                              for f in rep["findings"]]}))
    before = lstg.read_bytes()
    code, out = _fix(d, legacy)
    assert code == 1 and "legacy batch is never edited" in out["refused"]
    assert lstg.read_bytes() == before


def test_a_staging_file_changed_while_it_runs_is_not_overwritten(window, monkeypatch):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="verify")))
    _check(d, b)
    real = autofix._error_fields

    def meanwhile(row):
        stg.write_text(stg.read_text() + "\n")
        return real(row)

    monkeypatch.setattr(autofix, "_error_fields", meanwhile)
    code, out = _fix(d, b)
    assert code == 1 and "changed while autofix ran" in out["refused"] and _qa_files(d, b) == []


# ── never overwritten: each run numbered ─────────────────────────────────────

def test_each_run_is_numbered_and_earlier_records_are_kept(window):
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="verify")))
    _check(d, b)
    assert _fix(d, b)[0] == 0
    first = {n: (d / "_qa" / n).read_bytes() for n in _qa_files(d, b)}
    _edit(stg, (1, _set(evidence_grade="Help")))
    _check(d, b)
    code, out = _fix(d, b)
    assert code == 0 and out["fixed"] == {"evidence_grade_spelling": 1}
    assert _qa_files(d, b) == sorted([f"{b}.autofix-1.json", f"{b}.autofix-2.json",
                                      f"{b}.staging-before-autofix-1.md", f"{b}.staging-before-autofix-2.md"])
    assert all((d / "_qa" / n).read_bytes() == v for n, v in first.items())


def test_the_record_does_not_read_as_a_verdict_from_other_code(window):
    """g6 reads every json in _qa/: the record carries the manifest like the report."""
    d, b, stg = _staged(window)
    _edit(stg, (0, _set(evidence_grade="verify")))
    _check(d, b)
    _fix(d, b)
    rec = json.loads((d / "_qa" / f"{b}.autofix-1.json").read_text())
    assert rec["manifest_sha256"] == report.MANIFEST_SHA256 and "inputs" not in rec


def test_the_cli_dispatches_autofix(window, capsys):
    d, b, stg = _staged(window)
    assert cli.main(["autofix", "--subject", str(d), "--batch", b]) == 1
    assert "no check report" in json.loads(capsys.readouterr().out)["refused"]


@pytest.mark.parametrize("value,expected", [
    ("help", "help"), ("HELP", "help"), (" marketing ", "marketing"), ("Official - Doc", "official-doc"),
    ("verify", "[verify]"), ("[VERIFY]", "[verify]"), ("verified", "verified"),
    ("official doc", None), ("official_doc", None), ("verfied", None), ("", None), (None, None), (3, None)])
def test_the_known_respellings(value, expected):
    from kbqa.profiles.vendor_catalogue import schema_evidence_grade
    assert schema_evidence_grade(value) == expected
