"""Generate tests/fixtures/ deterministically.

Fixtures are AUTHORED, not harvested. Ground truth is controlled here, so
`good/` is known-good rather than assumed-good and every `bad_*` case fails
for exactly one known reason.

Note the deliberate vendor typo "definiton" in the capture. A row quotes it
verbatim. If anyone ever "helpfully" normalises spelling in G3, that fixture
breaks — which is the point.

Run:  python tests/build_fixtures.py
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from kbqa.models import SCHEMA_VERSION  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

OVERVIEW = "https://docs.acme.test/widgets/overview"
SYNTAX = "https://docs.acme.test/widgets/syntax-reference"
BILLING_SYNTAX = "https://docs.acme.test/billing/syntax-reference"
GHOST = "https://docs.acme.test/widgets/never-fetched"

CAPTURE = f"""=====BEGIN {OVERVIEW}=====
Widgets Overview

Acme Widgets let you compose reusable UI blocks. Each widget is scoped to a
workspace and can be exported as JSON.
=====END {OVERVIEW}=====
=====BEGIN {SYNTAX}=====
Widget Syntax Reference

A widget definiton must declare a `type` field.
=====END {SYNTAX}=====
"""


def row(**kw):
    # `id` MUST serialise first: the §G2 naive cross-check is `grep -c '^{"id"'`,
    # so a row that does not start with {"id" is invisible to it.
    base = {
        "id": "acme.widgets",
        # Follows the contract rather than pinning a literal: a fixture that
        # hardcodes a version silently rots into testing a schema nobody ships.
        "schema_version": SCHEMA_VERSION,
        "vendor_term": "Widgets",
        "what_it_does": "Compose reusable UI blocks scoped to a workspace.",
        "source_url": OVERVIEW,
        "source_quote": "Acme Widgets let you compose reusable UI blocks.",
        "access_date": "2026-08-23",
        "evidence_grade": "official-doc",
        "confidence": "high",
        "mechanism": "Native",
        "outcome": "yes",
        "depth_level": "module",
    }
    base.update(kw)
    return base


ROW_OVERVIEW = row()
ROW_SYNTAX = row(
    id="acme.widgets.syntax",
    vendor_term="Widget Syntax",
    what_it_does="Every widget declares a type field.",
    source_url=SYNTAX,
    # Verbatim, including the vendor's typo. Never corrected.
    source_quote="A widget definiton must declare a `type` field.",
    depth_level="feature",
    parent_path="Widgets",
)

DENOMINATOR = f"""# Acme docs index — widgets surface

- [Widgets Overview]({OVERVIEW})
- [Syntax Reference]({SYNTAX})
"""

DENOMINATOR_WITH_GAP = DENOMINATOR + f"- [Never Fetched]({GHOST})\n"

DENOMINATOR_COLLIDING = f"""# Acme docs index — colliding labels

- [Syntax Reference]({SYNTAX})
- [Syntax Reference]({BILLING_SYNTAX})
"""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def staging(rows, capture_text=CAPTURE, capture_name="_capture-widgets.raw.txt",
            pages=(OVERVIEW, SYNTAX), fetched_by_this_agent=False,
            capture_sha=None, extra_lines=""):
    sha = capture_sha if capture_sha is not None else sha256_text(capture_text)
    page_lines = "\n".join(f"  - {p}" for p in pages)
    body = "\n".join(json.dumps(r) for r in rows)
    return f"""---
batch: widgets
vendor: Acme
source_capture: {capture_name}
source_capture_sha256: {sha}
pages:
{page_lines}
fetched_by_this_agent: {"true" if fetched_by_this_agent else "false"}
---

# Staging — Acme widgets batch
{extra_lines}
{body}
"""


def write(name: str, files: dict):
    d = FIXTURES / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for fname, content in files.items():
        (d / fname).write_text(content, encoding="utf-8")


def build():
    FIXTURES.mkdir(parents=True, exist_ok=True)

    # ── must PASS every gate ──────────────────────────────────────────────
    write("good", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([ROW_OVERVIEW, ROW_SYNTAX]),
        "_denominator-docs-2026-08-23.md": DENOMINATOR,
        "_stop-conditions.md": "",
    })

    # ── G3 failures ───────────────────────────────────────────────────────
    write("bad_quote_not_in_capture", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([
            row(source_quote="Acme Widgets are the best way to build modular interfaces."),
            ROW_SYNTAX,
        ]),
        "_denominator-docs-2026-08-23.md": DENOMINATOR,
    })

    write("bad_url_not_in_capture", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([
            row(source_url=GHOST),
            ROW_SYNTAX,
        ]),
        "_denominator-docs-2026-08-23.md": DENOMINATOR,
    })

    # The quote is real and IS in the capture — but on the other page.
    # Whole-capture matching would bless this. Per-page scoping must not.
    write("bad_quote_from_wrong_page", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([
            row(source_quote="A widget definiton must declare a `type` field."),
            ROW_SYNTAX,
        ]),
        "_denominator-docs-2026-08-23.md": DENOMINATOR,
    })

    # ── G1 failures ───────────────────────────────────────────────────────
    write("bad_missing_capture", {
        "_collect-widgets-staging.md": staging([ROW_OVERVIEW, ROW_SYNTAX]),
        "_denominator-docs-2026-08-23.md": DENOMINATOR,
    })

    write("bad_capture_hash", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging(
            [ROW_OVERVIEW, ROW_SYNTAX], capture_sha="0" * 64
        ),
    })

    write("bad_unbalanced_markers", {
        "_capture-widgets.raw.txt": CAPTURE.replace(f"=====END {SYNTAX}=====\n", ""),
        "_collect-widgets-staging.md": staging([ROW_OVERVIEW, ROW_SYNTAX]),
    })

    # Capture written AFTER staging — rows cannot have come from it.
    write("bad_capture_after_staging", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([ROW_OVERVIEW, ROW_SYNTAX]),
    })

    # ── G2 failures ───────────────────────────────────────────────────────
    write("bad_enum", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([
            row(evidence_grade="blog"),
            ROW_SYNTAX,
        ]),
    })

    write("bad_zero_rows", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([]),
    })

    write("bad_duplicate_id", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([
            ROW_OVERVIEW,
            row(source_url=SYNTAX,
                source_quote="A widget definiton must declare a `type` field."),
        ]),
    })

    # extra="forbid": an invented field is a defect, not a warning.
    write("bad_extra_field", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([
            row(confidence_note="pretty sure"),
            ROW_SYNTAX,
        ]),
    })

    write("bad_id_pattern", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([
            row(id="Acme_Widgets"),
            ROW_SYNTAX,
        ]),
    })

    # ── G4 failures ───────────────────────────────────────────────────────
    write("bad_incomplete", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([ROW_OVERVIEW, ROW_SYNTAX]),
        "_denominator-docs-2026-08-23.md": DENOMINATOR_WITH_GAP,
    })

    write("bad_stop_without_reason", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([ROW_OVERVIEW, ROW_SYNTAX]),
        "_denominator-docs-2026-08-23.md": DENOMINATOR_WITH_GAP,
        "_stop-conditions.md": f"- {GHOST}\n",
    })

    write("good_with_stop", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([ROW_OVERVIEW, ROW_SYNTAX]),
        "_denominator-docs-2026-08-23.md": DENOMINATOR_WITH_GAP,
        "_stop-conditions.md": f"- {GHOST}: 404 at fetch time on 2026-08-23\n",
    })

    # 16 pages named `syntax-reference` must not collapse to one.
    write("colliding_labels", {
        "_denominator-docs-2026-08-23.md": DENOMINATOR_COLLIDING,
        "_collect-widgets-staging.md": staging([ROW_OVERVIEW, ROW_SYNTAX]),
    })

    # ── G5 (advisory) ─────────────────────────────────────────────────────
    write("bundled_terms", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging([
            ROW_OVERVIEW,
            row(id="acme.widgets.dup", source_url=SYNTAX,
                source_quote="A widget definiton must declare a `type` field."),
        ]),
    })

    # ── G6 failures ───────────────────────────────────────────────────────
    write("bad_role_collapse", {
        "_capture-widgets.raw.txt": CAPTURE,
        "_collect-widgets-staging.md": staging(
            [ROW_OVERVIEW, ROW_SYNTAX], fetched_by_this_agent=True
        ),
    })

    write("bad_proof_count", {
        "feature-tree.md": (
            "---\nvendor: Acme\nproof: 7 rows\n---\n\n"
            + json.dumps(ROW_OVERVIEW) + "\n"
            + json.dumps(ROW_SYNTAX) + "\n"
        ),
    })

    write("good_proof_count", {
        "feature-tree.md": (
            "---\nvendor: Acme\nproof: 2 rows\n---\n\n"
            + json.dumps(ROW_OVERVIEW) + "\n"
            + json.dumps(ROW_SYNTAX) + "\n"
        ),
    })

    print(f"fixtures written to {FIXTURES}")


if __name__ == "__main__":
    build()
