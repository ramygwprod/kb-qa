"""v6.22.0 — a mapping file written by code, from the mapper's draft.

The mapper judges (the role as printed, its article, where the role came from,
the want and the "so that", the theme, the element ids, the confidence, the
status and its note); `kbqa mapstage` builds the story the operator's rulings
of 2026-10-18 fix — the role copied, "a"/"an" only when the mapper gave one,
"(APQC-closest)" right after the role exactly when the role is APQC-closest,
always "I want" — and copies each element's hierarchy id and name from the
list. A rejected line blocks the file, as a rejected draft blocks the staging
file: one correction round, then `--leave-out-rejects`, which still writes one
line per anchor. The two passes never meet.
"""

import contextlib
import io
import json
import shutil
from pathlib import Path

import pytest

from kbqa import cli, mapstage
from kbqa.gates import mapcheck

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "tests" / "fixtures" / "contract"
SRC = FX / "K5" / "pass"
B = "docs-2026-01-31"
ELEMENTS = FX / "ref" / "elements.jsonl"
CODEBOOK = FX / "ref" / "codebook.md"
ANCHORS = ["example.docs.inbox", "example.docs.reports", "example.docs.roles", "example.docs.api"]


def _draft(**over):
    """Pass A's reading of the K5 batch: a singular role, a plural one, a role
    from another row, and an APQC-closest role the operator is asked about."""
    lines = [
        {"id": "example.docs.inbox", "article": "an", "role": "agent", "role_source": "rbac-row", "actor": "B",
         "want": "to reply to every customer message in one place", "so_that": "", "theme": "I01",
         "theme_links": [], "pcf_ids": ["90001"], "confidence": "medium", "status": "mapped", "note": ""},
        {"id": "example.docs.reports", "article": "", "role": "admins", "role_source": "rbac-vendor:example.docs.roles",
         "actor": "B", "want": "reports of the conversations each team closed",
         "so_that": "each team's week is seen", "theme": "I06", "theme_links": ["I01"], "pcf_ids": ["90002"],
         "confidence": "low", "status": "mapped", "note": ""},
        {"id": "example.docs.roles", "article": "an", "role": "admin", "role_source": "rbac-row", "actor": "B",
         "want": "to create custom roles", "so_that": "only the right people can change settings",
         "theme": "I07", "theme_links": [], "pcf_ids": ["90003"], "confidence": "high", "status": "mapped",
         "note": ""},
        {"id": "example.docs.api", "article": "a", "role": "developer", "role_source": "apqc-closest", "actor": "C",
         "want": "to send messages from their own systems", "so_that": "", "theme": "I11", "theme_links": [],
         "pcf_ids": ["90004"], "confidence": "low", "status": "needs-human", "note": "[Q4] person not stated"},
    ]
    for i, edit in over.items():
        lines[int(i[1:])].update(edit)
    return lines


@pytest.fixture
def subject(tmp_path):
    d = tmp_path / "Example"
    d.mkdir()
    shutil.copy(SRC / f"_collect-{B}-staging.md", d / f"_collect-{B}-staging.md")
    return d


def _write(d, letter, objs, raw=()):
    p = d / f"_mapdraft-{B}-{letter}.jsonl"
    p.write_text("".join(json.dumps(o) + "\n" for o in objs) + "".join(r + "\n" for r in raw))
    return p


def _run(d, letter="A", *extra):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = mapstage.run(["--subject", str(d), "--batch", B, "--pass", letter, "--elements", str(ELEMENTS),
                             *extra])
    return code, json.loads(out.getvalue())


def _map(d, letter="A"):
    return [json.loads(x) for x in (d / f"_map-{B}-{letter}.jsonl").read_text().splitlines() if x.strip()]


def _mapcheck(d, *letters):
    maps = [a for x in letters for a in ("--map", str(d / f"_map-{B}-{x}.jsonl"))]
    return mapcheck.run(["--staging", str(d / f"_collect-{B}-staging.md"), *maps, "--codebook", str(CODEBOOK),
                         "--elements", str(ELEMENTS), "--subject", str(d)])


# ── the file code writes passes the check ────────────────────────────────────

def test_both_passes_write_map_files_that_pass_mapcheck(subject):
    _write(subject, "A", _draft())
    _write(subject, "B", _draft(l1={"role": "agents", "article": ""}, l3={"theme": "I01", "status": "mapped",
                                                                          "note": ""}))
    for letter in "AB":
        code, r = _run(subject, letter)
        assert code == 0 and r["map"] and r["rejected"] == 0 and r["round"] == 1, r
    v, code = _mapcheck(subject, "A", "B")
    assert code == 0, [(f.code, f.message) for f in v.findings]
    assert v.counts["per_mapper"]["A"]["needs_human_by_pattern"] == {"Q4": ["example.docs.api"]}


def test_lines_are_in_the_mappers_key_order_and_the_staging_order(subject):
    _write(subject, "A", list(reversed(_draft())))
    assert _run(subject)[0] == 0
    lines = _map(subject)
    assert [x["id"] for x in lines] == ANCHORS
    assert all(list(x) == list(mapcheck.FIELDS) for x in lines)


def test_the_story_is_built_singular_plural_and_apqc_closest(subject):
    _write(subject, "A", _draft())
    assert _run(subject)[0] == 0
    stories = [x["user_story"] for x in _map(subject)]
    assert stories == [
        "As an agent, I want to reply to every customer message in one place",
        "As admins, I want reports of the conversations each team closed, so that each team's week is seen",
        "As an admin, I want to create custom roles, so that only the right people can change settings",
        "As a developer (APQC-closest), I want to send messages from their own systems",
    ]


def test_the_story_builder_alone():
    s = mapstage.user_story
    assert s("", "owners", "rbac-row", "x", "") == "As owners, I want x"
    assert s("a", "marketer", "apqc-closest", "x", "y") == "As a marketer (APQC-closest), I want x, so that y"
    assert s("an", "admin", "rbac-vendor:r.id", "x", "  ") == "As an admin, I want x"


def test_elements_are_copied_from_the_list_by_id(subject):
    _write(subject, "A", _draft(l0={"pcf_ids": ["90001", "90004"]}, l3={"pcf_ids": []}))
    assert _run(subject)[0] == 0
    listed = mapcheck.read_elements(ELEMENTS)
    assert _map(subject)[0]["pcf_ids"] == [
        {k: listed[i][k] for k in ("pcf_id", "hierarchy_id", "name")} for i in ("90001", "90004")]


def test_a_line_with_no_function_has_no_story(subject):
    _write(subject, "A", _draft(l3={"theme": "NO-FUNCTION", "role": "", "role_source": "", "actor": "",
                                    "article": "", "want": "", "pcf_ids": []}))
    assert _run(subject)[0] == 0
    assert _map(subject)[3]["user_story"] == ""
    v, code = _mapcheck(subject, "A")
    assert code == 0, [(f.code, f.message) for f in v.findings]


def test_the_cli_dispatches_mapstage(subject, capsys):
    _write(subject, "A", _draft())
    assert cli.main(["mapstage", "--subject", str(subject), "--batch", B, "--pass", "A",
                     "--elements", str(ELEMENTS)]) == 0
    assert json.loads(capsys.readouterr().out)["map"]


# ── rejected lines block the file ────────────────────────────────────────────

def _drop(i, *keys):
    def edit(lines):
        for k in keys:
            lines[i].pop(k)
        return lines
    return edit


REJECTS = {
    "unknown element id": (lambda l: l[0].update(pcf_ids=["99999"]) or l, "'99999' not in the element list"),
    "missing field": (_drop(1, "so_that"), "missing so_that"),
    "user_story is code's": (lambda l: l[1].update(user_story="As admins, I want x") or l,
                             "keys a draft line does not carry: user_story"),
    "an id not in the staging file": (lambda l: l + [dict(l[0], id="example.docs.nope")],
                                      "'example.docs.nope' is not a row of"),
    "a second line for one id": (lambda l: l + [dict(l[0])], "already has a line (line 1)"),
    "article not a, an or empty": (lambda l: l[0].update(article="the") or l, "article 'the'"),
    "needs-human note without its pattern": (lambda l: l[3].update(note="person not stated") or l,
                                             "opens with the rule or open pattern"),
    "a null": (lambda l: l[2].update(role=None) or l, "null in role"),
    "text that is not text": (lambda l: l[2].update(want=7) or l, "not text: want"),
    "element ids that are not text": (lambda l: l[2].update(pcf_ids=[90003]) or l, "not a list of element ids"),
    "no want outside no-function": (lambda l: l[2].update(want="") or l, "want is empty"),
    "a want without a role": (lambda l: l[2].update(role="") or l, "role is empty"),
    "an anchor with no line": (lambda l: l[:3], "'example.docs.api' has no line"),
}


@pytest.mark.parametrize("case", sorted(REJECTS))
def test_a_rejected_line_blocks_the_map_file(subject, case):
    edit, reason = REJECTS[case]
    _write(subject, "A", edit(_draft()))
    code, r = _run(subject)
    assert code == 1 and r["map"] is None and not (subject / f"_map-{B}-A.jsonl").exists(), r
    assert any(reason in x["reason"] for x in r["rejected_lines"]), r["rejected_lines"]
    rejects = subject / f"_mapdraft-{B}-A.rejects-1.jsonl"
    assert r["rejects"] == str(rejects) and rejects.is_file()
    assert "correction round" in r["next_step"]


def test_a_line_that_is_not_json_is_rejected(subject):
    _write(subject, "A", _draft(), raw=["{not json"])
    code, r = _run(subject)
    assert code == 1 and any("not JSON" in x["reason"] for x in r["rejected_lines"])


def test_a_line_for_another_source_is_rejected(subject):
    stg = subject / f"_collect-{B}-staging.md"
    stg.write_text(stg.read_text().replace(
        '"id": "example.docs.api"', '"id": "example.docs.api", "same_feature_as": "example.docs.inbox"'))
    _write(subject, "A", _draft())
    code, r = _run(subject)
    assert code == 1
    assert [x["reason"] for x in r["rejected_lines"]] == [
        "'example.docs.api' has same_feature_as: it takes its anchor's classification and gets no line"]
    _write(subject, "A", _draft()[:3])
    code, r = _run(subject)
    assert code == 0 and [x["id"] for x in _map(subject)] == ANCHORS[:3]


def test_a_batch_of_other_sources_only_writes_nothing(subject):
    stg = subject / f"_collect-{B}-staging.md"
    text = stg.read_text()
    for rid in ANCHORS:
        text = text.replace(f'"id": "{rid}"', f'"id": "{rid}", "same_feature_as": "example.other"')
    stg.write_text(text)
    code, r = _run(subject)
    assert code == 0 and r["map"] is None and "nothing to classify" in r["note"]
    assert not (subject / f"_map-{B}-A.jsonl").exists()


# ── rounds, and leaving out ──────────────────────────────────────────────────

def test_the_correction_round_writes_the_file(subject):
    _write(subject, "A", _draft(l0={"pcf_ids": ["99999"]}))
    assert _run(subject)[0] == 1
    _write(subject, "A", _draft())
    code, r = _run(subject)
    assert code == 0 and r["round"] == 2 and r["map"]
    assert (subject / f"_mapdraft-{B}-A.rejects-1.jsonl").is_file()  # each round's rejects kept


def test_after_the_correction_round_only_leave_out_remains(subject):
    _write(subject, "A", _draft(l0={"pcf_ids": ["99999"]}))
    code, r = _run(subject, "A", "--leave-out-rejects")
    assert code == 1 and "only after the mapper's correction round" in r["refused"]
    assert _run(subject)[0] == 1
    code, r = _run(subject)
    assert code == 1 and r["round"] == 2 and "--leave-out-rejects" in r["next_step"]
    code, r = _run(subject)
    assert code == 1 and "there is no second" in r["refused"] and "--leave-out-rejects" in r["next_step"]
    assert sorted(p.name for p in subject.glob(f"_mapdraft-{B}-A.rejects-*")) == [
        f"_mapdraft-{B}-A.rejects-1.jsonl", f"_mapdraft-{B}-A.rejects-2.jsonl"]
    assert not (subject / f"_map-{B}-A.jsonl").exists()


def _two_rounds(subject, lines, raw=()):
    _write(subject, "A", lines, raw)
    assert _run(subject)[0] == 1
    assert _run(subject)[0] == 1
    return _run(subject, "A", "--leave-out-rejects")


def test_leave_out_keeps_one_line_per_anchor(subject):
    lines = _draft(l0={"pcf_ids": ["99999", "90001"]})[:3] + [dict(_draft()[1], id="example.docs.nope")]
    code, r = _two_rounds(subject, lines, raw=["{not json"])
    assert code == 0 and r["round"] == 3 and (subject / f"_mapdraft-{B}-A.rejects-3.jsonl").is_file()
    out = _map(subject)
    assert [x["id"] for x in out] == ANCHORS  # every anchor, once — none dropped
    inbox, api = out[0], out[3]
    assert inbox["status"] == "needs-human"
    assert inbox["note"] == "[no rule] pcf_ids '99999' not in the element list"
    assert [e["pcf_id"] for e in inbox["pcf_ids"]] == ["90001"]  # the copyable reading is kept
    assert inbox["user_story"] == "As an agent, I want to reply to every customer message in one place"
    assert api["status"] == "needs-human" and api["note"] == "[no rule] the anchor row 'example.docs.api' has no line"
    assert out[1]["status"] == out[2]["status"] == "mapped"
    written = {(x.get("id"), x["written"]) for x in r["needs_operator"]}
    assert written == {("example.docs.inbox", "as a needs-human line"),
                       ("example.docs.api", "as a needs-human line"),
                       ("example.docs.nope", "not written: no anchor's line"),
                       (None, "not written: no anchor's line")}


def test_a_left_out_line_with_a_full_reading_passes_mapcheck(subject):
    code, r = _two_rounds(subject, _draft(l0={"pcf_ids": ["99999", "90001"]}))
    assert code == 0
    v, code = _mapcheck(subject, "A")
    assert code == 0, [(f.code, f.message) for f in v.findings]
    assert v.counts["per_mapper"]["A"]["needs_human_by_pattern"] == {"no rule": ["example.docs.inbox"],
                                                                     "Q4": ["example.docs.api"]}


def test_a_left_out_anchor_with_no_reading_is_never_given_one(subject):
    """Code invents no role source, actor or theme: the check fails that row
    until the operator rules on it."""
    code, r = _two_rounds(subject, _draft()[:3])
    assert code == 0
    api = _map(subject)[3]
    assert (api["role_source"], api["actor"], api["theme"], api["user_story"]) == ("", "", "", "")
    v, code = _mapcheck(subject, "A")
    assert code == 1 and {f.code for f in v.findings} == {"role_source_empty", "actor_invalid", "theme_unknown"}


def test_a_map_file_is_never_overwritten(subject):
    _write(subject, "A", _draft())
    m = subject / f"_map-{B}-A.jsonl"
    m.write_text("kept\n")
    code, r = _run(subject)
    assert code == 1 and "never overwritten" in r["refused"] and m.read_text() == "kept\n"


# ── retiring a pass when the rows changed ────────────────────────────────────

def _retire(d, letter="A", *extra):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = mapstage.run(["--subject", str(d), "--batch", B, "--pass", letter, "--retire", *extra])
    return code, json.loads(out.getvalue())


def _change_rows(d):
    stg = d / f"_collect-{B}-staging.md"
    stg.write_text(stg.read_text().replace("in one place.", "in one shared place."))


def test_the_map_file_records_the_staging_it_was_written_from(subject):
    _write(subject, "A", _draft())
    code, r = _run(subject)
    meta = json.loads((subject / f"_map-{B}-A.meta.json").read_text())
    sha = mapstage._sha256(subject / f"_collect-{B}-staging.md")
    assert code == 0 and r["staging_sha256"] == meta["staging_sha256"] == sha
    assert meta["map_sha256"] == mapstage._sha256(subject / f"_map-{B}-A.jsonl")


def test_retire_moves_and_keeps_every_file_of_the_pass(subject):
    _write(subject, "A", _draft(l0={"pcf_ids": ["99999"]}))
    assert _run(subject)[0] == 1
    _write(subject, "A", _draft())
    assert _run(subject)[0] == 0
    names = [f"_map-{B}-A.jsonl", f"_map-{B}-A.meta.json", f"_mapdraft-{B}-A.jsonl",
             f"_mapdraft-{B}-A.rejects-1.jsonl"]
    before = {n: (subject / n).read_bytes() for n in names}
    _change_rows(subject)
    code, r = _retire(subject)
    dest = subject / "_qa" / f"retired-{B}-A-1"
    assert code == 0 and r["retired_to"] == str(dest), r
    assert sorted(Path(m["to"]).name for m in r["moved"]) == sorted(names)
    assert {n: (dest / n).read_bytes() for n in names} == before  # moved whole, nothing lost
    assert not any((subject / n).exists() for n in names)
    assert "fresh draft for pass A" in r["next_step"]
    _write(subject, "A", _draft())  # the pass starts again at round 1
    code, r = _run(subject)
    assert code == 0 and r["round"] == 1


def test_retired_folders_are_numbered_and_never_reused(subject):
    for n in (1, 2):
        _write(subject, "A", _draft())
        assert _run(subject)[0] == 0
        _change_rows(subject) if n == 1 else (subject / f"_collect-{B}-staging.md").write_text(
            (subject / f"_collect-{B}-staging.md").read_text() + "\n")
        code, r = _retire(subject)
        assert code == 0 and r["retired_to"].endswith(f"retired-{B}-A-{n}"), r
    assert (subject / "_qa" / f"retired-{B}-A-1" / f"_map-{B}-A.jsonl").is_file()
    (subject / "_qa" / f"retired-{B}-A-2").rename(subject / "_qa" / f"retired-{B}-A-7")
    _write(subject, "A", _draft())
    code, r = _retire(subject)  # a draft alone: no map to compare
    assert code == 0 and r["retired_to"].endswith(f"retired-{B}-A-8")


def test_retire_refuses_while_the_staging_is_unchanged(subject):
    _write(subject, "A", _draft())
    assert _run(subject)[0] == 0
    code, r = _retire(subject)
    assert code == 1 and "unchanged" in r["refused"]
    assert (subject / f"_map-{B}-A.jsonl").is_file() and not (subject / "_qa").exists()


def test_retire_refuses_a_map_file_without_its_record(subject):
    _write(subject, "A", _draft())
    assert _run(subject)[0] == 0
    (subject / f"_map-{B}-A.meta.json").unlink()
    _change_rows(subject)
    code, r = _retire(subject)
    assert code == 1 and "cannot be told" in r["refused"] and (subject / f"_map-{B}-A.jsonl").is_file()


def test_retire_refuses_with_nothing_to_retire_or_other_flags(subject):
    code, r = _retire(subject)
    assert code == 1 and "no map file, draft or rejects file" in r["refused"]
    code, r = _retire(subject, "A", "--elements", str(ELEMENTS))
    assert code == 1 and "a run of its own" in r["refused"]


def test_a_map_file_is_refused_while_the_old_one_is_there(subject):
    _write(subject, "A", _draft())
    assert _run(subject)[0] == 0
    code, r = _run(subject)
    assert code == 1 and "--retire" in r["next_step"]


def test_a_sidecar_left_alone_is_never_overwritten(subject):
    _write(subject, "A", _draft())
    (subject / f"_map-{B}-A.meta.json").write_text("kept\n")
    code, r = _run(subject)
    assert code == 1 and "never overwritten" in r["refused"]
    assert not (subject / f"_map-{B}-A.jsonl").exists()


def test_retire_touches_only_the_given_pass(subject):
    for letter in "AB":
        _write(subject, letter, _draft())
        assert _run(subject, letter)[0] == 0
    _write(subject, "B", _draft(l0={"pcf_ids": ["99999"]}))
    (subject / f"_mapdraft-{B}-B.rejects-1.jsonl").write_text("{}\n")
    b_files = {p.name: p.read_bytes() for p in subject.glob(f"_map*-{B}-B*")}
    _change_rows(subject)
    code, r = _retire(subject, "A")
    assert code == 0 and all("-A" in Path(m["to"]).name for m in r["moved"])
    assert {p.name: p.read_bytes() for p in subject.glob(f"_map*-{B}-B*")} == b_files
    assert sorted(p.name for p in (subject / "_qa").iterdir()) == [f"retired-{B}-A-1"]


# ── the passes stay independent ──────────────────────────────────────────────

def test_a_pass_never_reads_or_counts_the_other_pass(subject):
    _write(subject, "A", _draft(l0={"pcf_ids": ["99999"]}))
    (subject / f"_mapdraft-{B}-B.jsonl").mkdir()  # reading it would fail
    (subject / f"_map-{B}-B.jsonl").write_text("{}\n")
    for n in (1, 2):
        (subject / f"_mapdraft-{B}-B.rejects-{n}.jsonl").write_text("{}\n")
    code, r = _run(subject)
    assert code == 1 and r["round"] == 1, r  # B's two rounds are not A's
    _write(subject, "A", _draft())
    code, r = _run(subject)
    assert code == 0 and r["round"] == 2 and r["map"] == str(subject / f"_map-{B}-A.jsonl")
    assert (subject / f"_map-{B}-B.jsonl").read_text() == "{}\n"
