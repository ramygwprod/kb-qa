"""The three commands' contract, end to end, on files in the collector's formats.

`/kbqa-collect` writes what `agents/kbqa-fetcher.md`, `kbqa-row-writer.md` and
`kbqa-mapper.md` describe; `/kbqa-check` runs `check_subject.sh` over it;
`/kbqa-merge` appends a CLEAR batch. The collector is instructions, not code, so
this cannot run it — it writes a subject exactly as those instructions say and
runs the real check script and the real merge against it. When the agents'
formats and the gates disagree, this is where it shows.

Round 1 carries one fixable defect (an empty `parent_path`), so it is BLOCKED;
round 2 fixes it and is CLEAR; the merge then starts the tree. One row sits on a
page with no breadcrumb, so its `parent_path` and `depth_level` are `unknown`.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHECK = REPO / "skills" / "kbqa-check" / "scripts" / "check_subject.sh"
MERGE = REPO / "skills" / "kbqa-merge" / "scripts" / "merge.py"
B = "docs-2026-10-16-w01"
HOST = "https://docs.example.test"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")

# (path, breadcrumb or None, the page's text)
PAGES = [
    ("webhooks", "Docs > Webhooks", "Webhooks notify your server when a message is delivered."),
    ("retries", "Docs > Webhooks > Retries", "Failed webhook calls are retried for up to 24 hours."),
    ("templates", "Docs > Templates", "Templates let you reuse approved message layouts."),
    ("reports", None, "Delivery reports show every message's final status."),
    ("pricing", "Docs > Pricing", "See our plans on the pricing page."),
]
ELEMENTS = [{"pcf_id": f"1000{i}", "hierarchy_id": f"1.{i}", "name": n}
            for i, n in enumerate(["Deliver messages", "Retry delivery",
                                   "Manage templates", "Report delivery"], start=1)]


def _estate(root: Path) -> Path:
    cfg = {"subjects_dir": "Subjects",
           "logic_sheet": "ref/LOGIC-SHEET.md",
           "themes_codebook": "ref/codebook.md",
           "apqc_elements": "ref/elements.jsonl"}
    (root / "ref").mkdir(parents=True)
    (root / "kbqa-estate.json").write_text(json.dumps(cfg))
    (root / "ref" / "LOGIC-SHEET.md").write_text("# Logic sheet (synthetic)\n")
    (root / "ref" / "codebook.md").write_text("| code | theme |\n|---|---|\n| I01 | Messaging |\n| I02 | Automation |\n")
    (root / "ref" / "elements.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ELEMENTS))

    d = root / "Subjects" / "Example-Co"
    d.mkdir(parents=True)
    # kbqa-fetcher §2: the index, rung named, one item per line
    (d / "_denominator-docs-2026-10-16.md").write_text(
        f"Index: docs, rung 2 — {HOST}/\n" + "".join(f"- [{p.title()}]({HOST}/{p})\n" for p, _, _ in PAGES))
    # kbqa-fetcher §3: one block per page, breadcrumb first, as served
    cap = d / f"_capture-{B}.raw.txt"
    cap.write_text("".join(
        f"=====BEGIN {HOST}/{p}=====\n" + (f"{crumb}\n" if crumb else "") + f"{text}\n=====END {HOST}/{p}=====\n"
        for p, crumb, text in PAGES))
    t = cap.stat().st_mtime - 300
    os.utime(cap, (t, t))  # G1: the capture precedes the rows
    # kbqa-fetcher §4: two surfaces not published; the page that held no row
    (d / "_stop-conditions.md").write_text(
        "- https://www.example.test/ | surface product not published: the site lists only docs\n"
        "- https://www.example.test/ | surface help not published: no help centre is linked\n"
        f"- {HOST}/pricing | no feature: pricing page\n")
    _staging(d, fixed=False)
    # kbqa-mapper: two independent passes; pass B asks a human about one row
    for letter in "AB":
        (d / f"_map-{B}-{letter}.jsonl").write_text("".join(
            json.dumps({"id": f"example.docs.{p}",
                        "user_story": "As an operator, I want this so that messages are handled.",
                        "role": "operator", "role_source": "apqc-closest", "actor": "B",
                        "theme": "I01" if i < 2 else "I02", "theme_links": [],
                        "pcf_ids": [ELEMENTS[i]],
                        "confidence": "low" if (letter == "B" and i == 3) else "high",
                        "status": "needs-human" if (letter == "B" and i == 3) else "mapped",
                        "note": "fit is outside the current list" if (letter == "B" and i == 3) else ""}) + "\n"
            for i, (p, _, _) in enumerate(PAGES[:4])))
    return d


def _staging(d: Path, fixed: bool):
    """kbqa-row-writer §1–§2: frontmatter from the receipt, then one row per line."""
    sha = hashlib.sha256((d / f"_capture-{B}.raw.txt").read_bytes()).hexdigest()
    rows = []
    for p, crumb, text in PAGES[:4]:
        parent = crumb or "unknown"
        if p == "templates" and not fixed:
            parent = ""  # the round-1 defect: parent_path empty
        rows.append({"id": f"example.docs.{p}", "source_url": f"{HOST}/{p}", "source_quote": text,
                     "access_date": "2026-10-16", "vendor_term": p.title(), "what_it_does": text,
                     "parent_path": parent, "evidence_grade": "official-doc", "confidence": "high",
                     "mechanism": "Native", "outcome": "yes",
                     "depth_level": str(len(crumb.split(" > "))) if crumb else "unknown",
                     "canonical": "NOVEL"})
    fm = (f"---\nbatch: {B}\nsource_capture: _capture-{B}.raw.txt\nsource_capture_sha256: {sha}\npages:\n"
          + "".join(f"  - {HOST}/{p}\n" for p, _, _ in PAGES)
          + "fetched_by_this_agent: false\nwindow_offset: 0\nwindow_requested: 20\nwindow_returned: 5\n"
            "window_end: exhausted\naccess_date: 2026-10-16\n---\n")
    (d / f"_collect-{B}-staging.md").write_text(fm + "\n```json\n" + "\n".join(json.dumps(r) for r in rows) + "\n```\n")


def _check(d: Path, root: Path) -> str:
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '/usr/bin:/bin')}"}
    p = subprocess.run(["bash", str(CHECK), str(d), str(root)], capture_output=True, text=True, env=env)
    return p.stdout + p.stderr


def test_collect_check_fix_check_merge(tmp_path):
    root = tmp_path / "estate with spaces"
    d = _estate(root)

    out = _check(d, root)
    assert "surfaces: PASS" in out, out
    assert "status=BLOCKED  round=1" in out, out
    assert "fixable=1" in out, out

    _staging(d, fixed=True)  # the one fix round
    out = _check(d, root)
    assert "status=CLEAR  round=2" in out, out
    assert "mapcheck: PASS" in out, out
    assert out.count("g4_completeness: PASS") == 2, out  # coverage and windows
    assert "g5_bundles: ADVISORY" in out, out
    assert "NOT CHECKED" not in out, out

    p = subprocess.run([sys.executable, str(MERGE), "--vendor-dir", str(d), "--batch", B, "--new-tree"],
                       capture_output=True, text=True)
    assert p.returncode == 0 and "MERGED" in p.stdout, p.stdout + p.stderr
    assert "G6 after merge: nothing on this tree or batch" in p.stdout, p.stdout
    tree = (d / "feature-tree.md").read_text()
    assert "rows=4 · unique_ids=4" in tree
    assert "schema:       kbqa vendor-catalogue profile v" in tree, "a new tree cites the rules enforced on it"
