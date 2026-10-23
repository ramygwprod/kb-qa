"""The same-feature shortlist — anchors that may be the feature a page shows.

`kbqa stage --lists` writes `_raw/<batch>/SAME-FEATURE.md` before the
row-writer runs: per page of the window, up to `MAX_PER_PAGE` of the subject's
anchors (the feature tree and every staging file, rows without
`same_feature_as`) that share at least `MIN_SHARED` words with the page.

The words compared are normalised the same way on both sides: lowercase,
runs of letters and digits, minus the short fixed `STOP_WORDS` list and minus
words of `MIN_LEN - 1` characters or fewer. An anchor's words are those of its
`vendor_term`, `parameter` and `what_it_does`; a page's words are those of its
headings (the receipt's) and of its parameter-like tokens — identifiers that
contain `_` or are written in camelCase — in its parts' own lines. The score is
the number of words in common; candidates are ordered by score (highest
first), then id.

**Candidates only.** A shared word is not the same feature, and an anchor not
listed may still be one: the row-writer judges sameness from the subject's own
words on both rows, as before.
"""

import re
import unicodedata
from typing import Dict, Iterable, List, Set, Tuple

from .features import is_anchor

NAME = "SAME-FEATURE.md"
MAX_PER_PAGE = 10  # anchors listed per page, at most
MIN_SHARED = 2     # words in common for an anchor to be listed
MIN_LEN = 3        # words of 2 characters or fewer are not compared
# Words too common to say anything about a feature. Short and fixed: any word
# not here is compared.
STOP_WORDS = frozenset("""
about after all also and any are been but can could does each for from has have how into its
may more not only other our per than that the their them then there these they this those
was were what when where which who will with would you your
""".split())
ANCHOR_FIELDS = ("vendor_term", "parameter", "what_it_does")

WORD_RE = re.compile(r"[^\W_]+")              # a run of letters and digits
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CAMEL_RE = re.compile(r"[a-z][A-Z]")


def words(text: object) -> Set[str]:
    """The normalised words of a text: lowercase letters-and-digits runs, no
    stop word, none shorter than `MIN_LEN`."""
    s = unicodedata.normalize("NFKC", str(text)).lower()
    return {w for w in WORD_RE.findall(s) if len(w) >= MIN_LEN and w not in STOP_WORDS}


def parameter_like(text: str) -> List[str]:
    """Identifiers that look like a setting or field name: they contain `_`, or
    are camelCase (a lowercase letter followed by a capital)."""
    return [t for t in IDENT_RE.findall(text) if "_" in t or CAMEL_RE.search(t)]


def _union(sets: Iterable[Set[str]]) -> Set[str]:
    out: Set[str] = set()
    for s in sets:
        out |= s
    return out


def anchor_words(row: dict) -> Set[str]:
    return _union(words(row[k]) for k in ANCHOR_FIELDS if isinstance(row.get(k), str))


def page_words(page: dict, lines: List[str]) -> Set[str]:
    """A page's headings and the parameter-like tokens of its parts' own lines
    (`lines` is the capture's text, split; part lines are 1-based)."""
    heads = _union(words(h.get("text", "")) for h in page.get("headings") or [] if isinstance(h, dict))
    tokens: List[str] = []
    for part in page.get("parts") or []:
        a, b = part["lines"]
        tokens += parameter_like("\n".join(lines[a - 1:b]))
    return heads | _union(words(t) for t in tokens)


def candidates(anchors: Dict[str, Set[str]], page_w: Set[str]) -> List[Tuple[str, int, List[str]]]:
    """(id, score, words in common) of the anchors listed for one page."""
    scored = []
    for rid, aw in anchors.items():
        shared = aw & page_w
        if len(shared) >= MIN_SHARED:
            scored.append((rid, len(shared), sorted(shared)))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored[:MAX_PER_PAGE]


def _cell(value: object) -> str:
    return str(value if value is not None else "").replace("\n", " ")


def same_feature_list(batch: str, pages: List[dict], lines: List[str], rows: Dict[str, dict]) -> str:
    """The shortlist as markdown: one section per page of the window, in the
    receipt's order."""
    anchors = {rid: r for rid, r in rows.items() if is_anchor(r)}
    words_of = {rid: anchor_words(r) for rid, r in anchors.items()}
    out = [
        f"# Same-feature shortlist — {batch}",
        "",
        "Written by `kbqa stage --lists` from the receipt, the capture and the subject's anchors (the",
        "feature tree and every staging file). Per page of this window: up to "
        f"{MAX_PER_PAGE} anchors whose",
        "`vendor_term`, `parameter` and `what_it_does` share at least "
        f"{MIN_SHARED} words with the page's",
        "headings and its parameter-like tokens (identifiers with `_` or in camelCase), scored by",
        "the number of words in common. One line per candidate:",
        "`id | score | words in common | vendor_term | parent_path | what_it_does`.",
        "",
        "**Candidates only.** A shared word is not the same feature, and an anchor not listed here",
        "may still be one: judge sameness from the subject's own words on both rows.",
        "",
    ]
    for page in pages:
        out.append(f"## {page['url']}")
        found = candidates(words_of, page_words(page, lines))
        if not found:
            out.append(f"- no anchor shares {MIN_SHARED} words with this page")
        for rid, score, shared in found:
            r = anchors[rid]
            out.append("- " + " | ".join([rid, str(score), ", ".join(shared)]
                                         + [_cell(r.get(k)) for k in ("vendor_term", "parent_path",
                                                                      "what_it_does")]))
        out.append("")
    return "\n".join(out)
