"""G6 · Integrity — g6 --root <project>

Estate-wide checks that no single-batch gate can see:
  · the manifest recorded in the newest verdicts still matches this code
  · every feature-tree's `proof:` count matches its own content
  · no Bronze file changed after the verdict that vouched for it
  · no staging file attests `fetched_by_this_agent: true` (role collapse)

The manifest check is tamper-EVIDENCE, not tamper-proofing. It tells a human
that a verdict came from code other than the approved code. Only CI running
from a pinned version can prevent that. (spec §0)
"""

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..manifest import MANIFEST_SHA256, sha256_file
from ..parsing import parse_staging
from ..verdict import FAIL, PASS, Finding, Verdict
from . import EXIT_FAIL, EXIT_PASS

GATE = "g6_integrity"

BRONZE_PATTERNS = ("_robots-*.txt", "_capture-*.raw.txt", "_denominator-*.md")
PROOF_RE = re.compile(r"^proof:\s*(?P<val>.+?)\s*$", re.MULTILINE)
INT_RE = re.compile(r"\d+")
ROW_RE = re.compile(r'^\{"id"', re.MULTILINE)


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa g6")
    ap.add_argument("--root", required=True)
    args = ap.parse_args(argv)

    root = Path(args.root)
    findings: List[Finding] = []
    if not root.exists():
        findings.append(Finding("root_missing", f"not found: {root}"))
        return Verdict(GATE, FAIL, {"root": {"path": str(root)}}, {}, findings), EXIT_FAIL

    verdict_files = sorted(root.glob("**/_qa/*.json"))
    checked_verdicts = 0
    stale_manifest = 0

    # 1 · manifest recorded in the newest verdicts vs this code
    newest_by_gate = {}
    for vf in verdict_files:
        try:
            data = json.loads(vf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(Finding("verdict_unreadable", f"{vf}: {exc}", where=str(vf)))
            continue
        checked_verdicts += 1
        gate = data.get("gate", "<unknown>")
        prev = newest_by_gate.get(gate)
        if prev is None or vf.stat().st_mtime > prev[0]:
            newest_by_gate[gate] = (vf.stat().st_mtime, vf, data)

    for gate, (_mtime, vf, data) in sorted(newest_by_gate.items()):
        recorded = data.get("manifest_sha256")
        if recorded != MANIFEST_SHA256:
            stale_manifest += 1
            findings.append(
                Finding(
                    "manifest_mismatch",
                    f"newest {gate} verdict records manifest {recorded} but this code "
                    f"hashes to {MANIFEST_SHA256}; the verdict came from different code",
                    where=str(vf),
                )
            )

    # 2 · Bronze files modified after the verdict that vouched for them
    bronze_checked = 0
    for vf in verdict_files:
        try:
            data = json.loads(vf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        v_mtime = vf.stat().st_mtime
        for name, ref in (data.get("inputs") or {}).items():
            if not isinstance(ref, dict):
                continue
            p = ref.get("path")
            recorded_hash = ref.get("sha256")
            if not p or not recorded_hash:
                continue
            path = Path(p)
            if not any(path.match(pat) for pat in BRONZE_PATTERNS):
                continue
            if not path.exists():
                findings.append(
                    Finding("bronze_missing", f"{name} recorded in {vf.name} no longer exists: {p}", where=p)
                )
                continue
            bronze_checked += 1
            actual = sha256_file(path)
            if actual != recorded_hash:
                findings.append(
                    Finding(
                        "bronze_modified",
                        f"Bronze file changed after its verdict: {p} "
                        f"(verdict {vf.name} recorded {recorded_hash}, now {actual}). "
                        "Bronze is never edited — re-fetch to a new dated file instead.",
                        where=p,
                    )
                )
            elif path.stat().st_mtime > v_mtime:
                findings.append(
                    Finding(
                        "bronze_touched_after_verdict",
                        f"Bronze file mtime is newer than the verdict that vouched for it: {p}",
                        where=p,
                    )
                )

    # 3 · feature-tree proof counts
    trees = sorted(root.glob("**/feature-tree.md"))
    for tree in trees:
        text = tree.read_text(encoding="utf-8")
        m = PROOF_RE.search(text)
        if not m:
            continue
        digits = INT_RE.search(m.group("val"))
        if not digits:
            findings.append(
                Finding("proof_unparseable", f"{tree}: proof line has no row count", where=str(tree))
            )
            continue
        claimed = int(digits.group())
        actual = len(ROW_RE.findall(text))
        if claimed != actual:
            findings.append(
                Finding(
                    "proof_count_mismatch",
                    f"{tree}: proof claims {claimed} rows, file contains {actual}",
                    where=str(tree),
                )
            )

    # 4 · role collapse
    stagings = sorted(root.glob("**/_collect-*-staging.md"))
    for stg in stagings:
        fm = parse_staging(stg).frontmatter_raw
        if fm.get("fetched_by_this_agent") is True:
            findings.append(
                Finding(
                    "role_collapse",
                    f"{stg}: staging attests fetched_by_this_agent: true — the row-writer "
                    "fetched its own source. Rows and capture are not independent.",
                    where=str(stg),
                )
            )

    counts = {
        "verdicts": checked_verdicts,
        "gates_with_verdicts": len(newest_by_gate),
        "stale_manifest": stale_manifest,
        "bronze_checked": bronze_checked,
        "feature_trees": len(trees),
        "staging_files": len(stagings),
        "failed": len(findings),
    }
    verdict = PASS if not findings else FAIL
    return Verdict(GATE, verdict, {"root": {"path": str(root)}}, counts, findings), (
        EXIT_PASS if verdict == PASS else EXIT_FAIL
    )
