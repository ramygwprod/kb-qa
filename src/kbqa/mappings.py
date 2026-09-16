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
from .profile import active
from .profile import conventions as _conventions

RELATIONS = ("exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch")
STATUSES = ("unexamined", "examined-no-match", "mapped")
REQUIRED = ("id", "scheme", "status", "date")

EXIT_OK = 0
EXIT_FAIL = 1


class Corpus:
    """Where an id lives, and whether it means one thing.

    Ids were chosen as the mapping key because the merged layer holds 12,804
    rows with 12,804 distinct ids. Unioning staging back in reintroduces the
    ambiguity that choice avoided: measured on one estate, 126 `(subject, id)`
    pairs carry rows that disagree on the subject's own words depending on which
    layer you read — 49 differing on `vendor_term`, 119 on `source_url`.

    So the merged layer is the anchor. Staging is consulted for membership only,
    which is safe, and a statement about an id that has not merged yet is
    premature rather than wrong.
    """

    def __init__(self) -> None:
        self.tree_ids: Set[str] = set()
        self.staging_ids: Set[str] = set()
        self.ambiguous: Dict[str, Set[str]] = {}

    @property
    def all_ids(self) -> Set[str]:
        return self.tree_ids | self.staging_ids


def read_corpus(root: Path) -> Corpus:
    conv = _conventions()
    fields = active().verbatim_fields
    corpus = Corpus()
    seen: Dict[str, Dict[str, object]] = {}

    def scan(paths, into: Set[str]) -> None:
        for path in paths:
            try:
                parsed = parse_staging(path)
            except Exception:  # noqa: BLE001 — an unreadable file is not a mapping defect
                continue
            for rp in parsed.rows:
                if not rp.obj or not rp.obj.get("id"):
                    continue
                rid = str(rp.obj["id"])
                into.add(rid)
                shape = {f: rp.obj.get(f) for f in fields if f != "id"}
                if rid in seen:
                    differing = {
                        f for f, v in shape.items()
                        if f in seen[rid] and seen[rid][f] != v
                    }
                    if differing:
                        corpus.ambiguous.setdefault(rid, set()).update(differing)
                else:
                    seen[rid] = shape

    scan(sorted(root.glob("**/feature-tree*.md")), corpus.tree_ids)
    scan(sorted(root.glob(conv.staging_glob)), corpus.staging_ids)
    return corpus


def corpus_ids(root: Path) -> Set[str]:
    """Back-compatible membership set. Prefer `read_corpus` for anchoring."""
    return read_corpus(root).all_ids


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


def check(statements: List[dict], corpus: Optional[Corpus] = None) -> Tuple[List[str], Dict[str, int]]:
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

        if corpus is not None and corpus.all_ids:
            if rid not in corpus.all_ids:
                # A mapping about a row nobody holds is a statement about
                # nothing, and the likeliest cause is a typo that would
                # otherwise sit there looking like coverage.
                problems.append(f"line {n}: id {rid!r} is in no row in the corpus")
            elif rid in corpus.ambiguous:
                # The reason this key was chosen, arriving anyway.
                fields = ", ".join(sorted(corpus.ambiguous[rid]))
                problems.append(
                    f"line {n}: id {rid!r} names different things depending on "
                    f"which layer you read ({fields} disagree). A mapping on an "
                    "ambiguous id records a decision about an unknown subject — "
                    "resolve the collision first"
                )
            elif rid not in corpus.tree_ids:
                problems.append(
                    f"line {n}: id {rid!r} exists only in staging and has not "
                    "merged. A mapping attaches to a merged row; until then the "
                    "id is unexamined, which is true anyway"
                )

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
        "corpus_rows": len(corpus.tree_ids) if corpus else 0,
        "ambiguous_ids": len(corpus.ambiguous) if corpus else 0,
        **{f"status_{k}": v for k, v in sorted(status_counts.items())},
        "problems": len(problems),
    }
    return problems, counts


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa mappings")
    ap.add_argument(
        "--file", required=True, nargs="+",
        help="mapping statement files, one JSON object per line. Several are "
             "expected: the namespace is estate-wide, sharded one file per "
             "subject, because one writer per file is a standing constraint and "
             "a single estate-wide file is one nobody reads",
    )
    ap.add_argument("--root", default=None, help="estate root, to confirm every id exists")
    args = ap.parse_args(argv)

    paths = [Path(f) for f in args.file]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"mappings: not found: {p}")
        return EXIT_FAIL

    statements: List[dict] = []
    parse_errors: List[str] = []
    for p in paths:
        st, errs = read_statements(p)
        for s in st:
            s["_file"] = p.name
        statements.extend(st)
        parse_errors.extend(f"{p.name}: {e}" for e in errs)

    corpus: Optional[Corpus] = None
    if args.root:
        root = Path(args.root)
        if not root.is_dir():
            print(f"mappings: not a directory: {root}")
            return EXIT_FAIL
        corpus = read_corpus(root)
        if not corpus.all_ids:
            print(f"mappings: no rows found under {root}")
            print("  Every id would then look unknown, which is noise rather than a finding.")
            return EXIT_FAIL

    problems, counts = check(statements, corpus)
    problems = parse_errors + problems

    print(f"mapping statements: {counts['statements']} from {len(paths)} file(s)")
    if args.root:
        covered, total = counts["rows_with_a_statement"], counts["corpus_rows"]
        pct = (100 * covered // total) if total else 0
        print(f"  merged rows with a statement: {covered} of {total} ({pct}%)")
        if counts.get("ambiguous_ids"):
            # Named whether or not any mapping touches one: an id meaning two
            # things is a latent merge collision, and the merge step is the one
            # part of this pipeline with no code to audit.
            print(
                f"  ambiguous ids in the corpus: {counts['ambiguous_ids']} "
                "(the same id names different things in different layers)"
            )
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
