"""kbqa mapstage — a mapping file written by code, from the mapper's draft.

    python3 -m kbqa mapstage --subject <d> --batch <b> --pass <A|B> --elements <list>
                             [--leave-out-rejects]

**The mapper judges; code copies.** One mapping pass writes
`_mapdraft-<batch>-<A|B>.jsonl`, one JSON object per anchor row of the staging
file, with exactly these keys: `id`, `article` (`"a"`, `"an"` or `""`),
`role`, `role_source`, `actor`, `want`, `so_that`, `theme`, `theme_links`,
`pcf_ids` (element ids only, as text), `confidence`, `status`, `note`.

`kbqa mapstage` writes `_map-<batch>-<A|B>.jsonl` from it, in the mapper's
format (`gates.mapcheck.FIELDS`, in that order), one line per anchor in the
staging file's order, so nothing code can make is typed by an agent:

- `user_story` = `"As " + article + role + " (APQC-closest)" + ", I want " +
  want + ", so that " + so_that` — the article (and its space) only when the
  mapper gave one, the tag only when `role_source` is `apqc-closest`, the
  "so that" part only when `so_that` is not empty. A line with no story — its
  `theme` `NO-FUNCTION` or `NOT-FEATURE` and its `want` empty — gets `""`;
- each `pcf_ids` entry is `{pcf_id, hierarchy_id, name}`, all three copied from
  the element list by id;
- every other key is copied as written; `/kbqa-check` (mapcheck) judges them.

**A rejected line blocks the mapping file**, as a rejected draft blocks the
staging file (`kbqa stage`): a line that is not a JSON object; a key missing or
extra; a `null`; a text key that is not text; an `id` that is not an anchor row
of the staging file (not a row of it, or a row with `same_feature_as`), or that
has a line already; an `article` other than the three; a `pcf_ids` entry not on
the element list; a story that cannot be built (a `want` without a `role`, or
no `want` outside `NO-FUNCTION`/`NOT-FEATURE`); a `needs-human` note that does
not open with the rule or open pattern it stops on, in brackets. An anchor
with no line is rejected too. Each run that rejects writes only
`_mapdraft-<batch>-<A|B>.rejects-<n>.jsonl` (never overwritten) and exits 1.
The mapper has one correction round; then `--leave-out-rejects` writes the
mapping file with every anchor still on exactly one line: an anchor whose line
is rejected or missing is written `needs-human`, its note
`[no rule] <the reason>`, carrying what its draft gave that can be copied.
Rejected lines that are no anchor's line are not written; each is listed under
`needs_operator`, never dropped unseen.

**The two passes stay independent.** Only this pass's draft, rejects files and
mapping file are ever opened or counted — never the other letter's.

Beside the map file it writes `_map-<batch>-<A|B>.meta.json`: the staging
file's name and sha256 it was written from (also in the result as
`staging_sha256`). `mapcheck` never reads it.

**Classifying again, after the rows changed** (the fix round):

    python3 -m kbqa mapstage --subject <d> --batch <b> --pass <A|B> --retire [--no-record]

moves this pass's map file, its sidecar, its draft and every one of its rejects
files into a new `_qa/retired-<batch>-<A|B>-<n>/` (`n` from 1, one past every
earlier folder of this batch and pass; nothing deleted, nothing overwritten)
and prints what it moved and the next step: the mapper writes a fresh draft for
this pass. It refuses when the staging file still hashes to the sha256 the
sidecar recorded — classifying unchanged rows again is wasted work — and when
the bytes changed but the anchor ids did not: the ids of the rows without
`same_feature_as` now, against the ids the map file has lines for. Its result
says `anchor_set_changed`, with the ids added and removed. A map file with no
sidecar is refused too, unless `--no-record` is given — on the operator's word
only, for a map file written before sidecars existed: it is retired and
`RETIRED-WITHOUT-RECORD.txt` in the folder says so. It touches only the given
pass.

Prints one JSON result. Exit 0 when the file was written (or there is nothing
to classify) or the files were retired, 1 when refused or lines were rejected.
Never overwrites a mapping file.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .gates.mapcheck import APQC_TAG, FIELDS, NO_ROLE, note_pattern, read_elements
from .parsing import parse_staging
from .profile import conventions
from .stage import _write_new

PASSES = ("A", "B")
# The mapper's draft: its judgement only. `user_story` and the elements'
# hierarchy ids and names are made by code, so the draft never carries them.
DRAFT_FIELDS = ("id", "article", "role", "role_source", "actor", "want", "so_that", "theme",
                "theme_links", "pcf_ids", "confidence", "status", "note")
TEXT_FIELDS = ("id", "article", "role", "role_source", "want", "so_that", "status", "note")
ARTICLES = ("a", "an", "")
APQC_CLOSEST = "apqc-closest"
NEEDS_HUMAN = "needs-human"
LEFT_OUT_PATTERN = "[no rule]"
CORRECTION_ROUNDS = 1  # the mapper corrects rejected lines once; there is no second round
LEAVE_OUT = "--leave-out-rejects"
RETIRE = "--retire"
NO_RECORD = "--no-record"
NO_RECORD_NOTE = "RETIRED-WITHOUT-RECORD.txt"
BATCH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ANCHOR_NEXT = ("the mapper corrects this line in its one correction round; still rejected, the anchor is "
               "written needs-human for the operator")
OTHER_NEXT = ("the mapper removes or corrects this line in its one correction round; a line that is no "
              "anchor's is never written")


class Refused(Exception):
    def __init__(self, message: str, next_step: str = "operator"):
        super().__init__(message)
        self.next_step = next_step


def draft_name(batch: str, letter: str) -> str:
    return f"_mapdraft-{batch}-{letter}.jsonl"


def map_name(batch: str, letter: str) -> str:
    return f"_map-{batch}-{letter}.jsonl"


def rejects_name(batch: str, letter: str, round_no: int) -> str:
    return f"_mapdraft-{batch}-{letter}.rejects-{round_no}.jsonl"


def meta_name(batch: str, letter: str) -> str:
    """The sidecar beside a map file: the staging sha256 it was written from."""
    return f"_map-{batch}-{letter}.meta.json"


def retired_dir_re(batch: str, letter: str) -> "re.Pattern":
    return re.compile(re.escape(f"retired-{batch}-{letter}-") + r"(\d+)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def user_story(article: str, role: str, role_source: str, want: str, so_that: str) -> str:
    """The story, built: "As [a|an ]<role>[ (APQC-closest)], I want <want>[, so that <so_that>]"."""
    story = "As " + (f"{article} " if article else "") + role
    if role_source == APQC_CLOSEST:
        story += f" {APQC_TAG}"
    story += f", I want {want}"
    if so_that.strip():
        story += f", so that {so_that}"
    return story


def story_problem(obj: dict) -> Optional[str]:
    """Why no story can be built from the line, or None. No `want` means no
    story, which only a NO-FUNCTION or NOT-FEATURE line may have."""
    if not obj["want"].strip():
        if obj.get("theme") not in NO_ROLE:
            return (f"want is empty, so there is no story: only a line whose theme is "
                    f"{' or '.join(NO_ROLE)} has none")
        return None
    if not obj["role"].strip():
        return "role is empty: a story needs the role it opens with"
    return None


def story_of(obj: dict) -> str:
    if not obj["want"].strip():
        return ""
    return user_story(obj["article"], obj["role"], obj["role_source"], obj["want"], obj["so_that"])


def pcf_entries(ids: List[str], elements: Dict[str, dict]) -> List[dict]:
    """Each id's {pcf_id, hierarchy_id, name}, copied from the element list."""
    out = []
    for i in ids:
        e = elements[i]
        out.append({"pcf_id": e["pcf_id"], "hierarchy_id": e["hierarchy_id"], "name": e["name"]})
    return out


def _rounds(subject: Path, batch: str, letter: str) -> List[Path]:
    """This pass's rejects files so far — never the other pass's."""
    prefix = f"_mapdraft-{batch}-{letter}.rejects-"
    found = []
    for p in subject.glob(f"{prefix}*.jsonl"):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)\.jsonl", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return [p for _, p in sorted(found)]


def _round_of(p: Path) -> int:
    return int(p.name.rsplit("-", 1)[1].split(".")[0])


def _command(subject: Path, batch: str, letter: str, elements: Path, *extra: str) -> str:
    return " ".join([f'python3 -m kbqa mapstage --subject "{subject}" --batch {batch} --pass {letter} '
                     f'--elements "{elements}"', *extra])


def _anchors(staging: Path) -> Tuple[List[str], set]:
    """The staging file's anchor ids in its order, and its other sources' ids."""
    rows = [r.obj for r in parse_staging(staging).rows if r.obj and r.obj.get("id")]
    others = {str(o["id"]) for o in rows if o.get("same_feature_as")}
    return [str(o["id"]) for o in rows if str(o["id"]) not in others], others


def _check(obj: dict, elements: Dict[str, dict]) -> List[str]:
    """What is wrong with one draft line, apart from its id; [] when nothing."""
    missing = [k for k in DRAFT_FIELDS if k not in obj]
    extra = [k for k in obj if k not in DRAFT_FIELDS]
    if missing or extra:
        why = []
        if missing:
            why.append(f"missing {', '.join(missing)}")
        if extra:
            why.append(f"keys a draft line does not carry: {', '.join(extra)}"
                       + (" (code writes user_story and the elements' names)"
                          if {"user_story"} & set(extra) else ""))
        return ["; ".join(why)]
    nulls = [k for k in DRAFT_FIELDS if obj[k] is None]
    if nulls:
        return [f"null in {', '.join(nulls)}: empty is \"\" or []"]
    not_text = [k for k in TEXT_FIELDS if not isinstance(obj[k], str)]
    if not_text:
        return [f"not text: {', '.join(not_text)}"]
    reasons = []
    if obj["article"] not in ARTICLES:
        reasons.append(f"article {obj['article']!r} is not \"a\", \"an\" or \"\"")
    pcfs = obj["pcf_ids"]
    if not isinstance(pcfs, list) or not all(isinstance(i, str) for i in pcfs):
        reasons.append("pcf_ids is not a list of element ids as text")
    else:
        unknown = [i for i in pcfs if i not in elements]
        if unknown:
            reasons.append(f"pcf_ids {', '.join(map(repr, unknown))} not in the element list")
    problem = story_problem(obj)
    if problem:
        reasons.append(problem)
    if obj["status"] == NEEDS_HUMAN and note_pattern(obj["note"]) is None:
        reasons.append("a needs-human note opens with the rule or open pattern it stops on, in brackets: "
                       "`[<name>] <why>`")
    return reasons


def _line(obj: dict, elements: Dict[str, dict]) -> dict:
    """A map line from an accepted draft line, in the mapper's key order."""
    built = dict(obj, user_story=story_of(obj), pcf_ids=pcf_entries(obj["pcf_ids"], elements))
    return {k: built[k] for k in FIELDS}


def _left_out_line(rid: str, obj: Optional[dict], reason: str, elements: Dict[str, dict]) -> dict:
    """An anchor whose line is rejected or missing: written needs-human, its
    note the reason, with what its draft gave that can be copied as it is."""
    obj = obj if isinstance(obj, dict) else {}

    def text(k: str, default: str = "") -> str:
        return obj[k] if isinstance(obj.get(k), str) else default

    ids = obj.get("pcf_ids") if isinstance(obj.get("pcf_ids"), list) else []
    links = obj.get("theme_links")
    parts = {k: text(k) for k in ("article", "role", "role_source", "want", "so_that")}
    story = ""
    if parts["article"] in ARTICLES and parts["want"].strip() and parts["role"].strip():
        story = user_story(**parts)
    line = {"id": rid, "user_story": story, "role": parts["role"], "role_source": parts["role_source"],
            "actor": text("actor"), "theme": text("theme"),
            "theme_links": [t for t in links if isinstance(t, str)] if isinstance(links, list) else [],
            "pcf_ids": pcf_entries([i for i in ids if isinstance(i, str) and i in elements], elements),
            "confidence": text("confidence", "low"), "status": NEEDS_HUMAN,
            "note": f"{LEFT_OUT_PATTERN} {reason}"}
    return {k: line[k] for k in FIELDS}


def mapstage(subject: Path, batch: str, letter: str, elements_path: Path,
             leave_out: bool = False) -> Tuple[int, Dict[str, object]]:
    if not subject.is_dir():
        raise Refused(f"no subject folder {subject}")
    if not BATCH_NAME_RE.match(batch):
        raise Refused(f"batch {batch!r} is not a batch name")
    if letter not in PASSES:
        raise Refused(f"pass {letter!r} is not A or B")
    staging = subject / conventions().staging_for(batch)
    if not staging.is_file():
        raise Refused(f"no staging file {staging.name}: kbqa stage writes it first")
    if not elements_path.is_file():
        raise Refused(f"no element list {elements_path}")
    elements = read_elements(elements_path)
    if not elements:
        raise Refused(f"the element list {elements_path} holds no element")
    out_path = subject / map_name(batch, letter)
    meta_path = subject / meta_name(batch, letter)
    for p in (out_path, meta_path):
        if p.exists():
            raise Refused(f"{p.name} already exists — a mapping file is never overwritten; when the rows changed, "
                          f"{RETIRE} moves this pass's files aside first",
                          next_step=f'python3 -m kbqa mapstage --subject "{subject}" --batch {batch} '
                                    f"--pass {letter} {RETIRE} — only when the staging file changed since")
    anchors, others = _anchors(staging)
    result: Dict[str, object] = {"batch": batch, "pass": letter, "staging": str(staging)}
    if not anchors:
        result.update(map=None, note="every row of the batch has same_feature_as: nothing to classify, so no "
                                     "mapping file is written")
        return 0, result
    draft_path = subject / draft_name(batch, letter)
    if not draft_path.is_file():
        raise Refused(f"no draft {draft_path.name}: the mapper writes it first")
    cmd = _command(subject, batch, letter, elements_path)
    earlier = _rounds(subject, batch, letter)
    if len(earlier) >= CORRECTION_ROUNDS + 1 and not leave_out:
        raise Refused(
            f"lines were rejected in {len(earlier)} runs ({', '.join(p.name for p in earlier)}) and the mapper's "
            "one correction round is used: there is no second",
            next_step=f"{cmd} {LEAVE_OUT} — writes the mapping file with each anchor whose line is still "
                      "rejected marked needs-human for the operator")
    if leave_out and len(earlier) < CORRECTION_ROUNDS + 1:
        raise Refused(
            f"{LEAVE_OUT} comes only after the mapper's correction round has left lines rejected "
            f"({len(earlier)} rejects file(s) so far, {CORRECTION_ROUNDS + 1} needed)",
            next_step=cmd + (" — then, if lines are rejected, the mapper's one correction round"
                             if not earlier else ""))
    round_no = max([_round_of(p) for p in earlier] or [0]) + 1

    anchor_set = set(anchors)
    rejects: List[dict] = []
    accepted: Dict[str, dict] = {}      # anchor id -> its accepted draft line
    drafted: Dict[str, Tuple[int, dict]] = {}  # anchor id -> (its line, its draft), accepted or not
    first_line: Dict[str, int] = {}
    anchor_reason: Dict[str, str] = {}  # anchor id -> why its line is rejected or missing
    raw_lines = draft_path.read_text(encoding="utf-8").splitlines()
    for n, raw in enumerate(raw_lines, start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            rejects.append({"line": n, "reason": f"not JSON: {exc.msg}", "next_step": OTHER_NEXT, "raw": raw})
            continue
        if not isinstance(obj, dict):
            rejects.append({"line": n, "reason": "not a JSON object", "next_step": OTHER_NEXT, "raw": raw})
            continue
        rid = obj.get("id")
        rid_s = rid if isinstance(rid, str) else None
        if rid_s is not None and rid_s in first_line:
            rejects.append({"line": n, "id": rid_s, "reason": f"id {rid_s!r} already has a line (line "
                            f"{first_line[rid_s]}): one line per anchor", "next_step": OTHER_NEXT, "draft": obj})
            continue
        if rid_s is not None:
            first_line[rid_s] = n
        if rid_s is not None and rid_s in others:
            rejects.append({"line": n, "id": rid_s, "reason": f"{rid_s!r} has same_feature_as: it takes its "
                            "anchor's classification and gets no line", "next_step": OTHER_NEXT, "draft": obj})
            continue
        if rid_s is None or rid_s not in anchor_set:
            rejects.append({"line": n, **({"id": rid_s} if rid_s is not None else {}),
                            "reason": f"id {rid!r} is not a row of {staging.name}", "next_step": OTHER_NEXT,
                            "draft": obj})
            continue
        drafted[rid_s] = (n, obj)
        reasons = _check(obj, elements)
        if reasons:
            anchor_reason[rid_s] = "; ".join(reasons)
            rejects.append({"line": n, "id": rid_s, "reason": anchor_reason[rid_s], "next_step": ANCHOR_NEXT,
                            "draft": obj})
            continue
        accepted[rid_s] = obj
    for rid in anchors:
        if rid not in drafted:
            anchor_reason[rid] = f"the anchor row {rid!r} has no line"
            rejects.append({"id": rid, "reason": anchor_reason[rid],
                            "next_step": "the mapper adds its line in its one correction round; still missing, "
                                         "it is written needs-human for the operator"})

    result.update({"round": round_no, "draft": str(draft_path), "anchors": len(anchors),
                   "accepted": len(accepted), "rejected": len(rejects), "map": None, "rejects": None})
    if rejects:
        rp = subject / rejects_name(batch, letter, round_no)
        _write_new(rp, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rejects).encode("utf-8"))
        result["rejects"] = str(rp)
        result["rejected_lines"] = [{k: r[k] for k in ("line", "id", "reason") if k in r} for r in rejects]
        if not leave_out:
            if round_no <= CORRECTION_ROUNDS:
                result["next_step"] = (f"the mapper's one correction round: it rewrites only the rejected lines of "
                                       f"{draft_path.name} and adds any missing anchor's line, then {cmd}")
            else:
                result["next_step"] = (f"{cmd} {LEAVE_OUT} — the correction round is used; each anchor whose line "
                                       "is still rejected is written needs-human for the operator")
            result["note"] = "lines were rejected, so no mapping file was written"
            return 1, result

    lines: List[dict] = []
    for rid in anchors:
        if rid in accepted:
            lines.append(_line(accepted[rid], elements))
            continue
        lines.append(_left_out_line(rid, drafted.get(rid, (0, None))[1], anchor_reason[rid], elements))
    if rejects:
        result["needs_operator"] = [
            {**r, "written": ("as a needs-human line" if r["next_step"] != OTHER_NEXT
                              else "not written: no anchor's line")}
            for r in rejects]
    staging_sha = _sha256(staging)
    _write_new(out_path, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines).encode("utf-8"))
    meta = {"batch": batch, "pass": letter, "map": out_path.name, "map_sha256": _sha256(out_path),
            "staging": staging.name, "staging_sha256": staging_sha}
    _write_new(meta_path, (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    result.update(map=str(out_path), meta=str(meta_path), staging_sha256=staging_sha)
    return 0, result


def _map_ids(path: Path) -> Optional[set]:
    """The ids a map file has lines for — the anchors it was written for — or
    None when a line cannot be read."""
    ids = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), str):
            return None
        ids.add(obj["id"])
    return ids


def retire(subject: Path, batch: str, letter: str, no_record: bool = False) -> Dict[str, object]:
    """Move this pass's map file, its sidecar, its draft and its rejects files
    into a new `_qa/retired-<batch>-<pass>-<n>/` — only when the staging file
    changed since the map file was written and its anchor ids changed with it.
    With `no_record` (on the operator's word), a map file written before
    sidecars existed is retired, and the folder says so. Nothing is deleted or
    overwritten; the other pass is never touched."""
    if not subject.is_dir():
        raise Refused(f"no subject folder {subject}")
    if not BATCH_NAME_RE.match(batch):
        raise Refused(f"batch {batch!r} is not a batch name")
    if letter not in PASSES:
        raise Refused(f"pass {letter!r} is not A or B")
    staging = subject / conventions().staging_for(batch)
    if not staging.is_file():
        raise Refused(f"no staging file {staging.name}")
    out_path, meta_path = subject / map_name(batch, letter), subject / meta_name(batch, letter)
    files = [p for p in (out_path, meta_path, subject / draft_name(batch, letter)) if p.exists()]
    files += _rounds(subject, batch, letter)
    if not files:
        raise Refused(f"pass {letter} of {batch} has no map file, draft or rejects file to retire")
    if no_record and (not out_path.exists() or meta_path.exists()):
        raise Refused(f"{NO_RECORD} retires only a map file that has no {meta_path.name}: "
                      + (f"{meta_path.name} is there, so retire without {NO_RECORD}" if meta_path.exists()
                         else f"there is no {out_path.name}"),
                      next_step=f'python3 -m kbqa mapstage --subject "{subject}" --batch {batch} --pass {letter} '
                                f"{RETIRE}" if meta_path.exists() else "operator")
    anchors_now = set(_anchors(staging)[0])
    changed: Optional[dict] = None
    if out_path.exists():
        mapped = _map_ids(out_path)
        if mapped is not None:
            changed = {"anchor_set_changed": mapped != anchors_now,
                       "anchors_added": sorted(anchors_now - mapped), "anchors_removed": sorted(mapped - anchors_now)}
    if out_path.exists() and not no_record:
        if not meta_path.is_file():
            raise Refused(f"{out_path.name} has no {meta_path.name}, so whether the staging file changed since it "
                          "was written cannot be told: the operator decides",
                          next_step=f'only on the operator\'s word: python3 -m kbqa mapstage --subject "{subject}" '
                                    f"--batch {batch} --pass {letter} {RETIRE} {NO_RECORD}")
        try:
            recorded = json.loads(meta_path.read_text(encoding="utf-8")).get("staging_sha256")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise Refused(f"{meta_path.name} cannot be read: {exc}")
        if recorded == _sha256(staging):
            raise Refused(f"{staging.name} is unchanged since {out_path.name} was written (staging sha256 "
                          f"{recorded}): classifying the same rows again is wasted work, so nothing was moved")
        if changed is None:
            raise Refused(f"{out_path.name} has a line that is not a JSON object with an id, so which anchors it "
                          "classified cannot be told: the operator decides")
        if not changed["anchor_set_changed"]:
            raise Refused(f"{staging.name} changed since {out_path.name} was written, but its anchor ids (rows "
                          "without same_feature_as) did not: there is nothing to re-map, so nothing was moved",
                          next_step=f"keep {out_path.name}: the classification stands for the same anchors; "
                                    "/kbqa-check the batch again")
    qa = subject / "_qa"
    qa.mkdir(exist_ok=True)
    pat = retired_dir_re(batch, letter)
    used = [int(m.group(1)) for p in qa.iterdir() for m in [pat.fullmatch(p.name)] if m]
    n = max(used or [0]) + 1
    dest = qa / f"retired-{batch}-{letter}-{n}"
    dest.mkdir()  # a new folder: never reused
    moved = []
    for p in files:
        target = dest / p.name
        if target.exists():  # pragma: no cover — the folder is new
            raise Refused(f"{target} exists: nothing is overwritten")
        p.rename(target)
        moved.append({"from": str(p), "to": str(target)})
    out: Dict[str, object] = {"batch": batch, "pass": letter, "retired_to": str(dest), "moved": moved}
    if no_record:
        note = dest / NO_RECORD_NOTE
        _write_new(note, (
            f"{out_path.name} was retired without a record: it had no {meta_path.name}, so whether "
            f"{staging.name} changed since it was written could not be told by code. It was retired on the "
            f"operator's word ({RETIRE} {NO_RECORD}). {staging.name} hashed to {_sha256(staging)} when it was "
            "retired.\n").encode("utf-8"))
        out["without_record"] = str(note)
    out["anchor_set_changed"] = changed["anchor_set_changed"] if changed is not None else None
    if changed is not None:
        out.update(anchors_added=changed["anchors_added"], anchors_removed=changed["anchors_removed"])
    out["next_step"] = (f"the mapper writes a fresh draft for pass {letter} ({draft_name(batch, letter)}), "
                        f"then kbqa mapstage --pass {letter}; the other pass runs on its own")
    return out


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa mapstage")
    ap.add_argument("--subject", required=True, help="the subject folder")
    ap.add_argument("--batch", required=True, help="the batch whose staging file was classified")
    ap.add_argument("--pass", required=True, dest="letter", choices=PASSES, help="the mapping pass, A or B")
    ap.add_argument("--elements", help="the APQC element list (jsonl) the ids are copied from")
    ap.add_argument(LEAVE_OUT, action="store_true", dest="leave_out",
                    help="after the one correction round: write the mapping file, each anchor whose line is "
                         "still rejected marked needs-human, each reject listed under needs_operator")
    ap.add_argument(RETIRE, action="store_true", dest="retire",
                    help="when the staging file and its anchor ids changed since the map file was written: move "
                         "this pass's map, draft and rejects files into _qa/retired-<batch>-<pass>-<n>/")
    ap.add_argument(NO_RECORD, action="store_true", dest="no_record",
                    help="with --retire, on the operator's word only: retire a map file that has no .meta.json "
                         "(written before kbqa 6.22.0)")
    args = ap.parse_args(argv)
    try:
        if args.no_record and not args.retire:
            raise Refused(f"{NO_RECORD} is given with {RETIRE} only")
        if args.retire:
            if args.leave_out or args.elements:
                raise Refused(f"{RETIRE} is a run of its own: no --elements, no {LEAVE_OUT}")
            code, out = 0, retire(Path(args.subject), args.batch, args.letter, args.no_record)
        elif not args.elements:
            raise Refused("--elements is needed: the element list the ids are copied from")
        else:
            code, out = mapstage(Path(args.subject), args.batch, args.letter, Path(args.elements), args.leave_out)
    except Refused as exc:
        print(json.dumps({"batch": args.batch, "pass": args.letter, "refused": str(exc),
                          "next_step": exc.next_step}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


def main() -> None:  # pragma: no cover
    sys.exit(run())
