"""v6.18.1 — the mapping check follows the operator's rulings of 2026-10-18.

* The story copies `role` exactly, singular or plural ("As admins, I want…");
  "a" / "an" only before a singular role; always "I want".
* An APQC-closest role is followed by "(APQC-closest)" in the story, and no
  other role is.
* A needs-human note names the rule or open pattern it stops on, in brackets,
  so the check groups the rows and the operator answers each question once.
"""

import json
import subprocess
import sys
from pathlib import Path

from kbqa.gates import mapcheck

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "tests" / "fixtures" / "contract"
B = "docs-2026-01-31"
SRC = FX / "K5" / "pass"


def _objs(letter="A"):
    return [json.loads(ln) for ln in (SRC / f"_map-{B}-{letter}.jsonl").read_text().splitlines() if ln.strip()]


def _run(tmp_path, edit_a, edit_b=None):
    maps = []
    for letter, edit in (("A", edit_a), ("B", edit_b)):
        if letter == "B" and edit is None:
            continue
        objs = _objs(letter)
        edit(objs)
        m = tmp_path / f"_map-{B}-{letter}.jsonl"
        m.write_text("".join(json.dumps(o) + "\n" for o in objs))
        maps += ["--map", str(m)]
    return mapcheck.run(["--staging", str(SRC / f"_collect-{B}-staging.md"), *maps,
                         "--codebook", str(FX / "ref" / "codebook.md"),
                         "--elements", str(FX / "ref" / "elements.jsonl")])


def _codes(v, code):
    return [f.message for f in v.findings if f.code == code]


def test_the_fixture_passes_as_it_stands(tmp_path):
    v, code = _run(tmp_path, lambda o: None)
    assert code == 0, [(f.code, f.message) for f in v.findings]


def test_a_plural_role_needs_no_article(tmp_path):
    def edit(objs):
        objs[0]["role"] = "admins"
        objs[0]["user_story"] = "As admins, I want the shared inbox"
    v, _ = _run(tmp_path, edit)
    assert not _codes(v, "story_role_mismatch")


def test_a_singular_role_may_keep_its_article(tmp_path):
    def edit(objs):
        objs[0]["user_story"] = "As an admin, I want the shared inbox"
    v, _ = _run(tmp_path, edit)
    assert not _codes(v, "story_role_mismatch")


def test_the_role_must_still_be_the_lines_role(tmp_path):
    def edit(objs):
        objs[0]["user_story"] = "As agents, I want the shared inbox"
    v, _ = _run(tmp_path, edit)
    msgs = _codes(v, "story_role_mismatch")
    assert len(msgs) == 1 and "agents" in msgs[0]


def test_we_want_is_not_the_story_form(tmp_path):
    def edit(objs):
        objs[0]["user_story"] = "As admins, we want the shared inbox"
    v, _ = _run(tmp_path, edit)
    msgs = _codes(v, "story_role_mismatch")
    assert len(msgs) == 1 and "does not open" in msgs[0]


def test_an_apqc_closest_role_carries_the_tag(tmp_path):
    def edit(objs):
        objs[3]["user_story"] = "As an admin I want example.docs.api so that \"work\""
    v, code = _run(tmp_path, edit)
    msgs = _codes(v, "story_role_mismatch")
    assert code == 1 and len(msgs) == 1 and "(APQC-closest)" in msgs[0]


def test_the_tag_marks_an_apqc_closest_role_only(tmp_path):
    def edit(objs):
        objs[0]["user_story"] = "As an admin (APQC-closest), I want the shared inbox"
    v, code = _run(tmp_path, edit)
    msgs = _codes(v, "story_role_mismatch")
    assert code == 1 and len(msgs) == 1 and "rbac-row" in msgs[0]


def test_a_tagged_story_with_another_role_still_fails(tmp_path):
    def edit(objs):
        objs[3]["user_story"] = "As a developer (APQC-closest), I want example.docs.api"
    v, _ = _run(tmp_path, edit)
    msgs = _codes(v, "story_role_mismatch")
    assert len(msgs) == 1 and "developer" in msgs[0]


def test_the_tag_words_are_not_listed_as_outside_words(tmp_path):
    v, _ = _run(tmp_path, lambda o: None)
    out = v.counts["per_mapper"]["A"]["story_words_outside_row_and_element"]
    assert not any(w in ("apqc", "closest") for x in out for w in x["words"])


def test_a_needs_human_note_names_its_pattern(tmp_path):
    def edit(objs):
        objs[3]["note"] = "person not stated"
    v, code = _run(tmp_path, edit)
    assert code == 1 and len(_codes(v, "needs_human_without_pattern")) == 1
    v, code = _run(tmp_path, lambda o: o[3].update(note="[Q4] person not stated"))
    assert code == 0 and not _codes(v, "needs_human_without_pattern")


def test_an_empty_bracket_is_not_a_name(tmp_path):
    v, _ = _run(tmp_path, lambda o: o[3].update(note="[ ] person not stated"))
    assert len(_codes(v, "needs_human_without_pattern")) == 1


def _three_questions(objs, notes):
    for i, note in notes.items():
        objs[i]["status"] = "needs-human"
        objs[i]["note"] = note


def test_needs_human_rows_are_grouped_into_one_question_per_pattern(tmp_path):
    v, _ = _run(tmp_path,
                lambda o: _three_questions(o, {0: "[Q4] a", 1: "[q4]  b", 3: "[P3] c"}),
                lambda o: _three_questions(o, {1: "[Q4] b", 2: "[step 3] d"}))
    a = v.counts["per_mapper"]["A"]["needs_human_by_pattern"]
    assert a == {"Q4": ["example.docs.inbox", "example.docs.reports"], "P3": ["example.docs.api"]}
    q = {x["pattern"]: x for x in v.counts["questions"]}
    assert set(q) == {"Q4", "P3", "step 3"}
    assert q["Q4"]["rows"] == ["example.docs.inbox", "example.docs.reports"]
    assert q["Q4"]["per_pass"] == {"A": ["example.docs.inbox", "example.docs.reports"],
                                   "B": ["example.docs.reports"]}
    assert v.counts["questions"][0]["pattern"] == "Q4"  # the largest question first


def test_a_note_naming_no_pattern_is_listed_never_dropped(tmp_path):
    v, _ = _run(tmp_path, lambda o: _three_questions(o, {0: "no name here"}))
    groups = v.counts["per_mapper"]["A"]["needs_human_by_pattern"]
    assert groups[mapcheck.UNNAMED] == ["example.docs.inbox"]


def test_the_check_prints_one_line_per_question(tmp_path):
    v, _ = _run(tmp_path,
                lambda o: _three_questions(o, {0: "[Q4] a", 1: "[Q4] b"}),
                lambda o: _three_questions(o, {1: "[Q4] b"}))
    out = subprocess.run([sys.executable, str(ROOT / "skills" / "kbqa-check" / "scripts" / "summ.py")],
                         input=v.to_json(), capture_output=True, text=True).stdout
    assert "question [Q4]: 2 rows (A 2, B 1)" in out, out
