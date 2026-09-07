"""G5 · Bundles — g5 --rows <f>... — ADVISORY, always exit 0.

Reports that the same vendor term appears at more than one URL. That is all.

⛔ Resolves nothing. A repeated name is an R2 question for a human. A
`usecase_of` guessed from string similarity is indistinguishable later from a
sourced one, so this gate never writes one. (spec §G5)
"""

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..parsing import normalise_for_match, parse_staging
from ..verdict import ADVISORY, Finding, Verdict, input_ref
from . import EXIT_PASS

GATE = "g5_bundles"


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa g5")
    ap.add_argument("--rows", required=True, nargs="+")
    args = ap.parse_args(argv)

    inputs = {}
    for i, r in enumerate(args.rows):
        inputs[f"rows[{i}]"] = input_ref(Path(r))

    term_urls: Dict[str, Set[str]] = defaultdict(set)
    term_display: Dict[str, str] = {}
    total_rows = 0

    for r in args.rows:
        p = Path(r)
        if not p.exists():
            continue
        for rp in parse_staging(p).rows:
            if rp.obj is None:
                continue
            total_rows += 1
            term = rp.obj.get("vendor_term")
            url = rp.obj.get("source_url")
            if not term or not url:
                continue
            key = normalise_for_match(term).casefold()
            term_urls[key].add(url)
            term_display.setdefault(key, term)

    findings: List[Finding] = []
    repeated = 0
    for key, urls in sorted(term_urls.items()):
        if len(urls) > 1:
            repeated += 1
            findings.append(
                Finding(
                    "term_at_multiple_urls",
                    f"vendor_term {term_display[key]!r} appears at {len(urls)} URLs: "
                    + ", ".join(sorted(urls)),
                    where=term_display[key],
                )
            )

    counts = {
        "rows": total_rows,
        "distinct_terms": len(term_urls),
        "terms_at_multiple_urls": repeated,
        "rows_beyond_one_per_term": max(0, total_rows - len(term_urls)),
        "failed": 0,
    }
    # Advisory. Always exit 0, whatever it found.
    return Verdict(GATE, ADVISORY, inputs, counts, findings), EXIT_PASS
