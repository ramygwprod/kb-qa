"""Site chrome — a host's header and footer, kept once instead of on every page.

Menus, footers and cookie notices repeat on every page of a site. Kept on each
page they fill the window's budget, they are read again for every part, and
they invite rows written from menu text that is not the page's content. So the
capture keeps them once: a run of lines that opens (or closes) most pages of a
host, identically, is written to `_chrome/<host>/<header|footer>-<sha12>.txt`,
and each page's capture text starts after it (or ends before it).

Nothing is lost and nothing is reworded:
- the raw bytes of every page are kept unchanged, as before;
- a page's full text is its chrome header + its capture text + its chrome
  footer, and the receipt records, per page, which chrome file and how many
  lines were taken from each end, so the rendering stays reproducible;
- a chrome file is named by the sha256 of its content, so it is written once
  and never overwritten.

What counts as chrome is decided by code, conservatively:
- only lines at the very start or end of a page, never in its middle;
- an identical run shared by at least CHROME_MIN_PAGES pages and by at least
  half of the host's pages in the window — or a run already kept for the host
  in an earlier window, so a window with one page on a host is still served;
- never the breadcrumb line or anything after it at the top, so `parent_path`
  is always on the page;
- never the whole page: a page that would be left empty keeps its full text.
"""

import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .fetch import host_of

CHROME_DIR = "_chrome"
CHROME_MIN_PAGES = 3
CHROME_SHARE = 0.5
MAX_EDGE_LINES = 400  # a header longer than this is not a header


def _write_once(path: Path, text: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)


def _known(subject: Path, host: str, edge: str) -> List[Tuple[str, ...]]:
    d = subject / CHROME_DIR / host
    out = []
    if d.is_dir():
        for f in sorted(d.glob(f"{edge}-*.txt")):
            out.append(tuple(f.read_text(encoding="utf-8").split("\n")))
    return out


def _detect(seqs: List[Tuple[List[str], int]], from_end: bool) -> Optional[Tuple[str, ...]]:
    """The longest run of lines shared, identically, at one end of enough pages.
    Each page comes with the most lines that may be taken from that end."""
    n = len(seqs)
    need = max(CHROME_MIN_PAGES, -(-n // 2))  # ceil(n * CHROME_SHARE) for 0.5
    if n < need:
        return None
    best: Optional[Tuple[str, ...]] = None
    for length in range(1, MAX_EDGE_LINES + 1):
        counts: Dict[Tuple[str, ...], int] = {}
        for seq, most in seqs:
            if most >= length:
                run = tuple(seq[-length:]) if from_end else tuple(seq[:length])
                counts[run] = counts.get(run, 0) + 1
        top = max(counts.items(), key=lambda kv: kv[1], default=(None, 0))
        if top[1] < need:
            break
        best = top[0]
    return best


def _header_limit(page: dict) -> int:
    """Lines at the top that may be chrome: everything before the breadcrumb."""
    crumb = page.get("_crumb")
    return len(page["_lines"]) if crumb is None else crumb


def strip_chrome(subject: Path, pages: List[dict]) -> List[Dict[str, object]]:
    """Take each host's chrome off its pages (in place) and keep it once.
    Returns the chrome files this window used, for the receipt."""
    used: Dict[str, Dict[str, object]] = {}
    hosts: Dict[str, List[dict]] = {}
    for p in pages:
        hosts.setdefault(host_of(p["url"]), []).append(p)
    for host, hp in hosts.items():
        # Never the whole page (one line always stays), never past the breadcrumb.
        heads = [(p["_lines"], min(_header_limit(p), len(p["_lines"]) - 1)) for p in hp]
        tails = [(p["_lines"], len(p["_lines"]) - 1) for p in hp]
        candidates = {
            "header": [c for c in [_detect(heads, False)] if c] + _known(subject, host, "header"),
            "footer": [c for c in [_detect(tails, True)] if c] + _known(subject, host, "footer"),
        }
        for p in hp:
            lines = p["_lines"]
            take = {"header": 0, "footer": 0}
            files = {"header": None, "footer": None}
            for edge in ("header", "footer"):
                limit = _header_limit(p) if edge == "header" else len(lines)
                for run in sorted(candidates[edge], key=len, reverse=True):
                    k = len(run)
                    if edge == "header":
                        fits = k <= limit and tuple(lines[:k]) == run
                    else:
                        fits = k <= len(lines) - take["header"] and tuple(lines[-k:]) == run
                    if fits and len(lines) - take["header"] - k > 0:
                        take[edge] = k
                        text = "\n".join(run)
                        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                        rel = f"{CHROME_DIR}/{host}/{edge}-{sha[:12]}.txt"
                        _write_once(subject / rel, text)
                        files[edge] = rel
                        used.setdefault(rel, {"file": rel, "host": host, "edge": edge, "lines": k,
                                              "sha256": sha, "first_page": p["url"]})
                        break
            h, f = take["header"], take["footer"]
            if h or f:
                p["_lines"] = lines[h:len(lines) - f]
                p["_heads"] = [(j - h, lvl, t) for j, lvl, t in p["_heads"] if h <= j < len(lines) - f]
                if p.get("_crumb") is not None:
                    p["_crumb"] = p["_crumb"] - h
            p["chrome"] = {"header": files["header"], "header_lines": h,
                           "footer": files["footer"], "footer_lines": f}
    return sorted(used.values(), key=lambda u: u["file"])
