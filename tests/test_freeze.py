"""Freeze must catch the one edit a mapping pass is tempted to make.

R2 maps a subject's term to a standard category. Two terms that nearly match
map more cleanly if one of them is tidied first — and nothing downstream
notices, because the row still parses, still conforms, and its quote still
matches the capture. The quote was never what got adjusted.

So the load-bearing test here is the negative one: an edited `vendor_term` must
be caught. A freeze that has never reported drift has not been tested.
"""

import json

import pytest

from kbqa import cli


def _estate(tmp_path, vendor_term="Widgets", parent_path="Platform"):
    root = tmp_path / "estate"
    d = root / "Competitors" / "Acme"
    d.mkdir(parents=True, exist_ok=True)
    row = {
        "id": "acme.widgets",
        "vendor_term": vendor_term,
        "what_it_does": "Compose reusable UI blocks.",
        "parent_path": parent_path,
        "source_url": "https://docs.acme.test/widgets",
        "source_quote": "Acme Widgets let you compose reusable UI blocks.",
        "access_date": "2026-08-23",
        "evidence_grade": "official-doc",
        "confidence": "high",
        "mechanism": "Native",
        "outcome": "yes",
        "depth_level": "feature",
    }
    (d / "_collect-widgets-staging.md").write_text(
        "---\nbatch: widgets\n---\n\n" + json.dumps(row) + "\n", encoding="utf-8"
    )
    return root, d


def test_an_edited_vendor_term_is_caught(tmp_path, capsys):
    """The fold. "Conversation API" tidied to match "Conversations API"."""
    root, d = _estate(tmp_path, vendor_term="Widgets")
    snap = tmp_path / "freeze.json"
    assert cli.main(["freeze", "--root", str(root), "--out", str(snap)]) == 0
    capsys.readouterr()

    _estate(tmp_path, vendor_term="Widget")  # one character, whole meaning

    code = cli.main(["freeze", "--root", str(root), "--check", str(snap)])
    out = capsys.readouterr().out
    assert code == 1
    assert "CHANGED      1" in out
    assert "acme.widgets" in out


def test_an_edited_parent_path_is_caught(tmp_path, capsys):
    """Re-nesting a subject's tree to fit ours is the structural version."""
    root, _ = _estate(tmp_path, parent_path="Platform")
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    capsys.readouterr()

    _estate(tmp_path, parent_path="Core Platform")

    assert cli.main(["freeze", "--root", str(root), "--check", str(snap)]) == 1
    assert "CHANGED      1" in capsys.readouterr().out


def test_changing_our_own_reading_is_allowed(tmp_path, capsys):
    """`canonical`, `confidence`, `mechanism` are ours. Mapping must be free.

    A freeze that locked the whole row would block the round it exists to
    protect — this is what makes it a guard rather than a freeze of everything.
    """
    root, d = _estate(tmp_path)
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    capsys.readouterr()

    f = d / "_collect-widgets-staging.md"
    text = f.read_text()
    row = json.loads(text.splitlines()[-1])
    row["canonical"] = "standard.ui.components"
    row["confidence"] = "medium"
    f.write_text("---\nbatch: widgets\n---\n\n" + json.dumps(row) + "\n", encoding="utf-8")

    code = cli.main(["freeze", "--root", str(root), "--check", str(snap)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "CHANGED      0" in out


def test_a_disappeared_row_fails(tmp_path, capsys):
    root, d = _estate(tmp_path)
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    capsys.readouterr()

    (d / "_collect-widgets-staging.md").write_text("---\nbatch: widgets\n---\n\n", encoding="utf-8")

    assert cli.main(["freeze", "--root", str(root), "--check", str(snap)]) == 1
    assert "DISAPPEARED  1" in capsys.readouterr().out


def test_an_appeared_row_is_reported_but_does_not_fail(tmp_path, capsys):
    """Collection legitimately adds rows; this command is useful mid-collection."""
    root, d = _estate(tmp_path)
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    capsys.readouterr()

    f = d / "_collect-widgets-staging.md"
    row = json.loads(f.read_text().splitlines()[-1])
    extra = dict(row, id="acme.widgets.syntax", vendor_term="Syntax")
    f.write_text(f.read_text() + json.dumps(extra) + "\n", encoding="utf-8")

    code = cli.main(["freeze", "--root", str(root), "--check", str(snap)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "appeared     1" in out


def test_freezing_nothing_is_an_error(tmp_path, capsys):
    """An empty snapshot would later compare clean against anything."""
    root = tmp_path / "empty"
    root.mkdir()
    assert cli.main(["freeze", "--root", str(root), "--out", str(tmp_path / "f.json")]) == 1
    assert "no rows found" in capsys.readouterr().out


def test_comparing_across_field_sets_is_refused(tmp_path, capsys):
    """Otherwise every row reports drift, which reads as catastrophe and is noise."""
    root, _ = _estate(tmp_path)
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    capsys.readouterr()

    doc = json.loads(snap.read_text())
    doc["verbatim_fields"] = ["id", "source_url"]
    snap.write_text(json.dumps(doc))

    assert cli.main(["freeze", "--root", str(root), "--check", str(snap)]) == 1
    assert "different field set" in capsys.readouterr().out


def test_the_snapshot_records_which_code_made_it(tmp_path):
    """A snapshot from unknown gate code is not a baseline."""
    root, _ = _estate(tmp_path)
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    doc = json.loads(snap.read_text())
    assert doc["manifest_sha256"] and doc["kbqa_version"] and doc["profile"]


# --------------------------------------------------------------------------
# An estate with no version control
# --------------------------------------------------------------------------

def test_a_drift_report_says_what_the_field_held(tmp_path, capsys):
    """Measured on the estate this was built for: no `.git` anywhere.

    A fingerprint answers "did this change" and cannot answer "to what". Told to
    restore from version control that does not exist, an operator has no
    referent — and the likeliest outcome is that they re-freeze, which records
    the edit as the new truth.
    """
    root, _ = _estate(tmp_path, vendor_term="Widgets")
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    capsys.readouterr()

    _estate(tmp_path, vendor_term="Widget")
    cli.main(["freeze", "--root", str(root), "--check", str(snap)])
    out = capsys.readouterr().out

    assert "frozen: 'Widgets'" in out, out
    assert "now   : 'Widget'" in out
    assert "Restore each field to its frozen value" in out
    assert "version control" not in out


def test_fingerprints_only_admits_it_cannot_recover(tmp_path, capsys):
    root, _ = _estate(tmp_path)
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap), "--fingerprints-only"])
    assert "not recoverable" in capsys.readouterr().out

    _estate(tmp_path, vendor_term="Widget")
    cli.main(["freeze", "--root", str(root), "--check", str(snap)])
    out = capsys.readouterr().out
    assert "cannot say what" in out
    assert "re-collected from its source" in out


def test_values_are_stored_by_default(tmp_path):
    import json as _json

    root, _ = _estate(tmp_path)
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    doc = _json.loads(snap.read_text())
    assert doc["stores_values"] is True
    row = doc["rows"]["acme.widgets"]
    assert row["values"]["vendor_term"] == "Widgets"
    assert row["values"]["source_quote"]


def test_re_freezing_is_never_offered_as_the_fix(tmp_path, capsys):
    """The request to re-freeze always arrives sounding reasonable."""
    root, _ = _estate(tmp_path)
    snap = tmp_path / "freeze.json"
    cli.main(["freeze", "--root", str(root), "--out", str(snap)])
    capsys.readouterr()
    _estate(tmp_path, vendor_term="Widget")
    cli.main(["freeze", "--root", str(root), "--check", str(snap)])
    assert "Never re-freeze" in capsys.readouterr().out
