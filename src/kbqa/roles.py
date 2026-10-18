"""Role-row candidates — rows of the subject that may name who uses a feature.

The mapper's role-source order reaches, after the row's own words, a row of
the same subject that names the role for the same feature (the operator's
ruling of 2026-10-18). Finding those rows by reading the whole tree is
expensive and uneven; this lists the candidates by code, so the mapper reads a
short list and judges each one — same feature or not — itself.

Which words mark a roles-and-permissions row is the estate's vocabulary, not
this tool's: the patterns come from the estate's `kbqa-estate.json`, key
`role_rows`, a list of `{"pattern": <regex>, "fields": [<row fields>]}`,
matched without case, any pattern on any of its fields (the union). With no
such key the list is not written, and the receipt says so: nothing is guessed.
A candidate is never a role source by itself — the mapper decides.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .features import subject_rows

CONFIG = "kbqa-estate.json"
KEY = "role_rows"


def estate_config(subject: Path) -> Optional[Path]:
    """The nearest `kbqa-estate.json` at or above the subject folder."""
    for d in [subject.resolve(), *subject.resolve().parents]:
        if (d / CONFIG).is_file():
            return d / CONFIG
    return None


def patterns(config: Optional[Path]) -> Tuple[List[Tuple["re.Pattern[str]", List[str]]], Optional[str]]:
    """(compiled patterns with their fields, why there are none)."""
    if config is None:
        return [], f"no {CONFIG} at or above the subject folder"
    try:
        spec = json.loads(config.read_text(encoding="utf-8")).get(KEY)
    except (json.JSONDecodeError, OSError) as exc:
        return [], f"{config.name} could not be read: {exc}"
    if not spec:
        return [], f"{config.name} names no `{KEY}` patterns"
    out = []
    for i, entry in enumerate(spec):
        try:
            fields = [str(f) for f in entry["fields"]]
            out.append((re.compile(entry["pattern"], re.IGNORECASE), fields))
        except (KeyError, TypeError, re.error) as exc:
            return [], f"{config.name} `{KEY}` entry {i} is not {{pattern, fields}} with a valid pattern: {exc}"
    return out, None


def candidates(subject: Path, pats) -> List[Dict[str, object]]:
    out = []
    for rid, row in sorted(subject_rows(subject).items()):
        for n, (rx, fields) in enumerate(pats, 1):
            hit = next(((f, m.group(0)) for f in fields
                        for m in [rx.search(str(row.get(f, "")))] if m), None)
            if hit:
                out.append({"id": rid, "vendor_term": row.get("vendor_term", ""),
                            "parent_path": row.get("parent_path", ""),
                            "same_feature_as": row.get("same_feature_as"),
                            "field": hit[0], "matched": hit[1], "pattern": n})
                break
    return out


def role_rows_list(subject: Path) -> Tuple[Optional[str], Optional[str]]:
    """(the markdown list, or None; why there is none)."""
    pats, why = patterns(estate_config(subject))
    if not pats:
        return None, why
    rows = candidates(subject, pats)
    head = [f"# Role-row candidates of this subject — {len(rows)} rows",
            "",
            f"Written by `kbqa capture` from the feature tree and every staging file, matched by the "
            f"`{KEY}` patterns of {CONFIG}. One line per row: `id | vendor_term | parent_path | "
            "matched words (field)`. A candidate is a role source only for **the same feature**, and "
            "only when its own words name the role — you decide; the list only finds them.",
            ""]
    body = []
    for r in rows:
        same = f" | same feature as {r['same_feature_as']}" if r["same_feature_as"] else ""
        body.append(f"- {r['id']} | {r['vendor_term']} | {r['parent_path']} | "
                    f"\"{r['matched']}\" ({r['field']}){same}")
    return "\n".join(head + body) + "\n", None
