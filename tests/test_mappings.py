"""Mapping statements are about rows, stored outside rows, keyed by id.

The keying is the load-bearing decision and it was settled by measurement, not
preference: keying on `vendor_term` folds 81% of a real corpus, because rows
sharing a term are not thereby the same concept. `g5_bundles` says so already
and refuses to resolve it. These tests pin the ruling so it cannot drift back.
"""

import json

import pytest

from kbqa import cli
from kbqa.mappings import RELATIONS, STATUSES, check


def _st(**kw):
    base = {
        "id": "acme.widgets", "scheme": "std-2026", "status": "mapped",
        "concept": "ui.components", "relation": "broadMatch",
        "date": "2026-09-16", "by": "operator",
    }
    base.update(kw)
    base["_line"] = kw.pop("_line", 1)
    return base


def test_a_well_formed_statement_passes():
    problems, counts = check([_st()], {"acme.widgets"})
    assert problems == []
    assert counts["status_mapped"] == 1


def test_mapped_without_a_concept_is_caught():
    problems, _ = check([_st(concept=None)], {"acme.widgets"})
    assert any("no concept" in p for p in problems)


def test_a_relation_outside_skos_is_caught():
    problems, _ = check([_st(relation="sortOfLike")], {"acme.widgets"})
    assert any("relation" in p for p in problems)


def test_an_unknown_status_is_caught():
    problems, _ = check([_st(status="probably")], {"acme.widgets"})
    assert any("status" in p for p in problems)


def test_no_match_without_a_reason_is_caught():
    """The rare claim that not even a broader concept fits.

    broadMatch covers the usual case, so this status asserted without a reason
    is where "hard to classify" quietly becomes "unique".
    """
    problems, _ = check(
        [_st(status="examined-no-match", concept=None, relation=None)],
        {"acme.widgets"},
    )
    assert any("note" in p for p in problems)


def test_no_match_with_a_reason_passes():
    problems, _ = check(
        [_st(status="examined-no-match", concept=None, relation=None,
             note="the subject's own index lists this outside every published category")],
        {"acme.widgets"},
    )
    assert problems == []


def test_a_statement_about_a_row_nobody_holds_is_caught():
    problems, _ = check([_st(id="acme.typo")], {"acme.widgets"})
    assert any("no row in the corpus" in p for p in problems)


def test_two_concepts_for_one_id_without_distinct_dates_is_caught():
    """A revision is legitimate; a tie is meaningless."""
    problems, _ = check(
        [_st(concept="a", _line=1), _st(concept="b", _line=2)],
        {"acme.widgets"},
    )
    assert any("supersedes" in p for p in problems)


def test_two_concepts_with_distinct_dates_is_a_revision_not_a_conflict():
    problems, _ = check(
        [_st(concept="a", date="2026-09-01", _line=1),
         _st(concept="b", date="2026-09-16", _line=2)],
        {"acme.widgets"},
    )
    assert problems == []


def test_the_relation_and_status_vocabularies_stay_separate():
    """Status is not a relation. "Related to nothing" is not a semantic link.

    Encoding examined-no-match as a sixth SKOS relation would make a non-relation
    into a relation, which is why SKOS leaves it out.
    """
    assert set(RELATIONS).isdisjoint(STATUSES)
    assert "examined-no-match" not in RELATIONS
    assert len(RELATIONS) == 5


def test_end_to_end_through_the_cli(tmp_path, capsys):
    root = tmp_path / "estate"
    d = root / "Competitors" / "Acme"
    d.mkdir(parents=True)
    row = {
        "id": "acme.widgets", "vendor_term": "Widgets",
        "what_it_does": "Compose blocks.", "source_url": "https://docs.acme.test/w",
        "source_quote": "Acme Widgets let you compose blocks.",
        "access_date": "2026-08-23", "evidence_grade": "official-doc",
        "confidence": "high", "mechanism": "Native", "outcome": "yes",
        "depth_level": "feature",
    }
    (d / "_collect-w-staging.md").write_text(
        "---\nbatch: w\n---\n\n" + json.dumps(row) + "\n", encoding="utf-8")

    mf = tmp_path / "_mappings.jsonl"
    mf.write_text(json.dumps({
        "id": "acme.widgets", "scheme": "std-2026", "status": "mapped",
        "concept": "ui.components", "relation": "broadMatch", "date": "2026-09-16",
    }) + "\n", encoding="utf-8")

    assert cli.main(["mappings", "--file", str(mf), "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "rows with a statement: 1 of 1" in out
    assert "cannot prove it supports the claim" in out


def test_malformed_json_is_reported_not_skipped(tmp_path, capsys):
    mf = tmp_path / "_mappings.jsonl"
    mf.write_text('{"id": "a", "scheme": "s"\n', encoding="utf-8")
    assert cli.main(["mappings", "--file", str(mf)]) == 1
    assert "invalid JSON" in capsys.readouterr().out
