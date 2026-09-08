"""The sweep's job is to be honest about what cannot be known.

It is easy to write an audit that quietly flatters the data — counting rows it
could not read as absent, or reporting a grounding result for a batch with no
capture. Both would produce a cleaner number and a false one.

So these tests mostly assert restraint: that a batch with no capture gets no
grounding claim, that unreadable batches are surfaced rather than dropped, and
that the audit never gates.
"""

import json
import os

import pytest

from kbqa import cli
from kbqa.sweep import UNVERIFIABLE, VERIFIABLE, audit_batch, batch_name

CAPTURE_MTIME = 1_000_000_000
STAGING_MTIME = 1_000_000_100


@pytest.fixture
def estate(tmp_path):
    """An estate of named vendors, mtimes ordered as a real run would leave them.

    Copies from the fixture source rather than through `fx`, so the same fixture
    can back two different vendors — which is the normal case in an estate.
    """
    from conftest import FIXTURES

    def _mk(**vendors):
        root = tmp_path / "estate"
        (root / "Competitors").mkdir(parents=True)
        for vendor, fixture in vendors.items():
            src = FIXTURES / fixture
            assert src.is_dir(), f"missing fixture {fixture}"
            dst = root / "Competitors" / vendor
            dst.mkdir()
            for p in src.iterdir():
                dst_p = dst / p.name
                dst_p.write_bytes(p.read_bytes())
                m = CAPTURE_MTIME if p.name.startswith("_capture-") else STAGING_MTIME
                os.utime(dst_p, (m, m))
        return root

    return _mk


def _audit(root):
    assert cli.main(["sweep", "--root", str(root)]) == 0
    return json.loads((root / "_qa-estate-audit.json").read_text())


# --------------------------------------------------------------------------
# The distinction the sweep exists to draw
# --------------------------------------------------------------------------

def test_batches_are_tiered_by_whether_a_capture_exists(estate):
    root = estate(Acme="good", Borax="bad_missing_capture")
    data = _audit(root)

    tiers = {b["vendor"]: b["tier"] for b in data["batches"]}
    assert tiers["Acme"] == VERIFIABLE
    assert tiers["Borax"] == UNVERIFIABLE


def test_no_grounding_claim_is_made_without_a_capture(estate):
    """Reporting grounded=False here would assert something unknowable."""
    root = estate(Borax="bad_missing_capture")
    data = _audit(root)

    b = data["batches"][0]
    assert b["tier"] == UNVERIFIABLE
    assert b["grounded"] is None, "a batch with no capture has no grounding result"
    assert b["ungrounded_rows"] is None


def test_grounding_is_reported_where_a_capture_exists(estate):
    root = estate(Acme="good", Cirrus="bad_quote_not_in_capture")
    data = _audit(root)

    by_vendor = {b["vendor"]: b for b in data["batches"]}
    assert by_vendor["Acme"]["grounded"] is True
    assert by_vendor["Cirrus"]["grounded"] is False
    assert by_vendor["Cirrus"]["ungrounded_rows"] >= 1


def test_conformance_runs_on_unverifiable_batches_too(estate):
    """G2 needs no capture, so an unverifiable batch is still checkable for shape."""
    root = estate(Borax="bad_missing_capture")
    data = _audit(root)
    assert data["batches"][0]["conformant"] is True


def test_schema_violations_are_counted_without_a_capture(estate):
    root = estate(Borax="bad_enum")
    data = _audit(root)
    b = data["batches"][0]
    assert b["schema_violations"] >= 1
    assert b["conformant"] is False


# --------------------------------------------------------------------------
# Honesty about what could not be read
# --------------------------------------------------------------------------

def test_unreadable_rows_are_surfaced_not_silently_dropped(estate, tmp_path):
    root = estate(Acme="good")
    stg = next((root / "Competitors" / "Acme").glob("_collect-*-staging.md"))
    stg.write_text(stg.read_text() + '\n{"id": "broken", \n', encoding="utf-8")

    data = _audit(root)
    b = data["batches"][0]
    assert b["rows_unparseable"] >= 1
    assert b["conformant"] is False, "a batch with unreadable rows is not conformant"


def test_totals_add_up(estate):
    root = estate(Acme="good", Borax="bad_missing_capture", Cirrus="bad_quote_not_in_capture")
    t = _audit(root)["totals"]
    assert t["batches"] == 3
    assert t["vendors"] == 3
    assert t["verifiable_batches"] + t["unverifiable_batches"] == t["batches"]
    assert t["verifiable_rows"] + t["unverifiable_rows"] == t["rows"]


# --------------------------------------------------------------------------
# Auditing is not gating
# --------------------------------------------------------------------------

def test_a_mostly_unverifiable_estate_does_not_fail_the_run(estate):
    """An estate that is largely uncheckable is a fact to record, not an error.

    Failing here would make the audit unrunnable in exactly the situation it
    was built for.
    """
    root = estate(A="bad_missing_capture", B="bad_missing_capture")
    assert cli.main(["sweep", "--root", str(root)]) == 0


def test_an_empty_root_fails(tmp_path):
    """Finding no batches means the root is wrong, not that the estate is clean."""
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert cli.main(["sweep", "--root", str(empty)]) == 1


def test_sweep_needs_a_root():
    assert cli.main(["sweep"]) == 1
    assert cli.main(["sweep", "--root", "/nonexistent"]) == 1


def test_sweep_never_exits_2(estate):
    """Exit 2 means DECLINED. An audit must never be readable as one."""
    root = estate(Borax="bad_missing_capture")
    assert cli.main(["sweep", "--root", str(root)]) != 2


# --------------------------------------------------------------------------
# Field evidence for the next schema version
# --------------------------------------------------------------------------

def test_field_values_flag_reports_fields_outside_the_contract(estate):
    root = estate(Acme="bad_extra_field")
    assert cli.main(["sweep", "--root", str(root), "--field-values"]) == 0
    data = json.loads((root / "_qa-estate-audit.json").read_text())

    assert data["fields"], "--field-values must collect a distribution"
    outside = {k for k, v in data["fields"].items() if not v["in_contract"]}
    assert outside, "a field the collector emits but the contract omits must be visible"


def test_field_values_is_off_by_default(estate):
    root = estate(Acme="good")
    data = _audit(root)
    assert data["fields"] == {}


def test_batch_name_derivation():
    from pathlib import Path
    assert batch_name(Path("/x/_collect-functions-guides-staging.md")) == "functions-guides"


def test_audit_batch_never_raises_on_a_corrupt_file(tmp_path):
    """An unreadable batch must be a result, not an exception that stops the sweep."""
    stg = tmp_path / "_collect-x-staging.md"
    stg.write_bytes(b"\xff\xfe not valid utf-8 \x00")
    rec = audit_batch(stg)
    assert rec["batch"] == "x"
    assert rec["tier"] == UNVERIFIABLE
