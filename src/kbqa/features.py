"""A subject's features: which rows are anchors, and the list the row-writer reads.

A feature has one anchor row — the first row written for it, wherever it was
seen first — and any number of further rows that say `same_feature_as: <anchor
id>`: the same feature found again on another page, through another way in (an
API operation, a settings screen), or in a later batch. Every such row is kept
and grounded; only the anchor is classified. The feature tree is append-only,
so a later source is never merged into an earlier row: it is a new row that
points at it. (The operator's rulings of 2026-10-18.)

`features_list` is what the row-writer reads to decide whether a feature is
already a row: the subject's anchors — id, the subject's own term, its
breadcrumb, what it does — built by code from the feature tree and every
staging file, grouped by breadcrumb with an outline of line ranges, so the
row-writer reads only the groups that could hold its page's features and never
the whole tree.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .parsing import parse_staging
from .profile import conventions

TREE = "feature-tree.md"
OUTLINE_DEPTH = 2  # breadcrumb segments that name a group in the outline


def subject_rows(subject: Path, skip: Optional[Path] = None) -> Dict[str, dict]:
    """{row id: row} from the subject's feature tree and every staging file —
    the tree first, so a row merged and still staged is read as merged. A
    file that cannot be parsed contributes the rows that can."""
    conv = conventions()
    paths = [subject / TREE] + sorted(subject.glob(f"{conv.staging_prefix}*{conv.staging_suffix}"))
    out: Dict[str, dict] = {}
    for p in paths:
        if not p.is_file() or (skip is not None and p.resolve() == skip.resolve()):
            continue
        for rp in parse_staging(p).rows:
            if rp.obj and rp.obj.get("id"):
                out.setdefault(str(rp.obj["id"]), rp.obj)
    return out


def is_anchor(row: dict) -> bool:
    return not row.get("same_feature_as")


def _group(parent_path: object) -> str:
    segs = [s.strip() for s in str(parent_path or "unknown").split(">") if s.strip()]
    return " > ".join(segs[:OUTLINE_DEPTH]) or "unknown"


def features_list(subject: Path) -> str:
    """The subject's anchors as a markdown list, grouped by breadcrumb, with an
    outline of each group's line range at the top. Every anchor is listed
    whole: the row-writer judges sameness from it, so nothing is cut."""
    anchors = [r for r in subject_rows(subject).values() if is_anchor(r)]
    groups: Dict[str, List[dict]] = {}
    for r in anchors:
        groups.setdefault(_group(r.get("parent_path")), []).append(r)
    order = sorted(groups)
    body: List[str] = []
    ranges: List[Tuple[str, int, int]] = []
    # The header and outline are written first; body line numbers are offset after.
    for g in order:
        start = len(body)
        body.append(f"## {g}")
        for r in sorted(groups[g], key=lambda x: str(x.get("id"))):
            body.append("- " + " | ".join(
                str(r.get(k, "")).replace("\n", " ") for k in ("id", "vendor_term", "parent_path", "what_it_does")))
        body.append("")
        ranges.append((g, start, len(body) - 2))
    head = [
        f"# Features of this subject — {len(anchors)} anchors in {len(order)} groups",
        "",
        "Written by `kbqa capture` from the feature tree and every staging file. One line per",
        "anchor: `id | vendor_term | parent_path | what_it_does`. A row for a feature already",
        "listed here carries `same_feature_as: <its id>`. Read the outline, then only the",
        "groups that could hold your page's features (offset and limit).",
        "",
        "## Outline",
    ]
    outline_at = len(head)
    head_len = outline_at + len(order) + 1
    for g, a, b in ranges:
        head.append(f"- {g}: lines {a + head_len + 1}–{b + head_len + 1}")
    head.append("")
    return "\n".join(head + body) + "\n"
