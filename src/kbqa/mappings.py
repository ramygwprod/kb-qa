"""Mapping statements — about rows, stored outside rows, keyed by id.

A mapping says "this row's concept corresponds to that concept in a standard."
It is our reading, not the subject's words, so it lives in its own file and
never touches the row. Writing it into the row would be an edit to evidence,
and `kbqa freeze` would correctly report it as one.

WHY `id` AND NOT THE TERM. An earlier proposal keyed on `vendor_term` — map a
term once, cover every row using it. Measured against a real corpus that folds
81% of it: 9,238 `(subject, term)` pairs carry more than one row, covering
22,517 rows, and 434 terms appear in more than one subject with one spanning 43.
Rows sharing a term are not thereby the same concept — bundles repeat a term on
purpose, which is precisely what `g5_bundles` reports and refuses to resolve:
"a repeated name is an R2 question for a human."

Grouping by term is how a human REVIEWS efficiently. The statement is still per
row, because that is where identity lives.

STATUS IS NOT A RELATION. "Examined and genuinely unmatched" is the absence of a
semantic link plus a recorded review state, so it is `status`, not a sixth
SKOS relation. That distinction is also what makes progress measurable: the
count of `unexamined` falls monotonically, and a stalled pass stops looking
like a finished one.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .parsing import parse_staging
from .profile import conventions as _conventions

RELATIONS = ("exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch")
STATUSES = ("unexamined", "examined-no-match", "mapped")
REQUIRED = ("id", "scheme", "status", "date")

EXIT_OK = 0
EXIT_FAIL = 1


def corpus_ids(root: Path) -> Set[str]:
    conv = _conventions()
    ids: Set[str] = set()
    for path in sorted(root.glob(conv.staging_glob)) + sorted(root.glob("**/feature-tree*.md")):
        try:
            parsed = parse_staging(path)
        except Exception:  # noqa: BLE001 — an unreadable file is not a mapping defect
            continue
        for rp in parsed.rows:
            if rp.obj and rp.obj.get("id"):
                ids.add(str(rp.obj["id"]))
    return ids


def read_statements(path: Path) -> Tuple[List[dict], List[str]]:
    statements: List[dict] = []
    errors: List[str] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {n}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(obj, dict):
            errors.append(f"line {n}: not an object")
            continue
        obj["_line"] = n
        statements.append(obj)
    return statements, errors


def check(statements: List[dict], known_ids: Set[str]) -> Tuple[List[str], Dict[str, int]]:
    problems: List[str] = []
    by_id_scheme: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    status_counts: Counter = Counter()

    for s in statements:
        n = s.get("_line")
        missing = [f for f in REQUIRED if not s.get(f)]
        if missing:
            problems.append(f"line {n}: missing {', '.join(missing)}")
            continue

        rid, status = str(s["id"]), str(s["status"])
        status_counts[status] += 1

        if known_ids and rid not in known_ids:
            # A mapping about a row nobody holds is a statement about nothing —
            # and the likeliest cause is a typo that would otherwise sit there
            # looking like coverage.
            problems.append(f"line {n}: id {rid!r} is in no row in the corpus")

        if status not in STATUSES:
            problems.append(
                f"line {n}: status {status!r} is not one of {', '.join(STATUSES)}"
            )
            continue

        if status == "mapped":
            if not s.get("concept"):
                problems.append(f"line {n}: status 'mapped' with no concept")
            rel = s.get("relation")
            if rel not in RELATIONS:
                problems.append(
                    f"line {n}: relation {rel!r} is not one of {', '.join(RELATIONS)}"
                )
        elif status == "examined-no-match":
            # The standing rule is that a unique feature still relates to some
            # broader category — `broadMatch` exists for exactly that. So this
            # status is the rare claim that not even a broader concept fits, and
            # a rare claim asserted without a reason is where "hard to classify"
            # quietly becomes "unique".
            if not str(s.get("note", "")).strip():
                problems.append(
                    f"line {n}: 'examined-no-match' needs a note saying why no "
                    "broader concept fits — broadMatch covers the usual case"
                )
            if s.get("concept"):
                problems.append(f"line {n}: 'examined-no-match' must name no concept")

        by_id_scheme[(rid, str(s["scheme"]))].append(s)

    for (rid, scheme), group in sorted(by_id_scheme.items()):
        concepts = {str(g.get("concept")) for g in group if g.get("concept")}
        if len(concepts) > 1:
            dates = {str(g.get("date")) for g in group}
            if len(dates) < len(group):
                # Two different answers for one row in one scheme is fine as a
                # revision and meaningless as a tie. Distinct dates say which
                # supersedes which; identical ones leave a reader guessing.
                problems.append(
                    f"id {rid!r} in scheme {scheme!r} maps to {len(concepts)} "
                    "different concepts without distinct dates, so no reading "
                    "says which supersedes which"
                )

    counts = {
        "statements": len(statements),
        "rows_with_a_statement": len({str(s["id"]) for s in statements if s.get("id")}),
        "corpus_rows": len(known_ids),
        **{f"status_{k}": v for k, v in sorted(status_counts.items())},
        "problems": len(problems),
    }
    return problems, counts


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa mappings")
    ap.add_argument("--file", required=True, help="mapping statements, one JSON object per line")
    ap.add_argument("--root", default=None, help="estate root, to confirm every id exists")
    args = ap.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"mappings: not found: {path}")
        return EXIT_FAIL

    statements, parse_errors = read_statements(path)
    known: Set[str] = set()
    if args.root:
        root = Path(args.root)
        if not root.is_dir():
            print(f"mappings: not a directory: {root}")
            return EXIT_FAIL
        known = corpus_ids(root)
        if not known:
            print(f"mappings: no rows found under {root}")
            print("  Every id would then look unknown, which is noise rather than a finding.")
            return EXIT_FAIL

    problems, counts = check(statements, known)
    problems = parse_errors + problems

    print(f"mapping statements: {counts['statements']}")
    if args.root:
        covered, total = counts["rows_with_a_statement"], counts["corpus_rows"]
        pct = (100 * covered // total) if total else 0
        print(f"  rows with a statement: {covered} of {total} ({pct}%)")
    for k, v in sorted(counts.items()):
        if k.startswith("status_"):
            print(f"  {k[len('status_'):]:<18} {v}")
    print(f"  problems: {len(problems)}")
    for p in problems[:30]:
        print(f"    {p}")
    if len(problems) > 30:
        print(f"    … and {len(problems) - 30} more")

    if not problems:
        # Said out loud, because a well-formed mapping file is the easiest thing
        # in this pipeline to mistake for a correct one.
        print()
        print("  Well-formed. Whether a mapping is RIGHT is not checked here and")
        print("  cannot be — the same limit as G3, which proves a quote is real")
        print("  and cannot prove it supports the claim.")
    return EXIT_FAIL if problems else EXIT_OK
