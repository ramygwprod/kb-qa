"""kbqa index — a surface's denominator, from the subject's own index, by code.

    python3 -m kbqa index --out <subject dir> --surface product|docs|help
                          --rung <1-5> --url <index url> [--html] [--path-prefix <p>]

Writes `_denominator-<surface>-<YYYY-MM-DD>.md`: a first line naming the surface,
the rung and the URL, then one line per index item in the index's own order and
words — the shapes `/kbqa-check` reads:

- **llms.txt / markdown** (rung 1): every line holding a markdown link, copied
  unchanged;
- **sitemap.xml** (rung 3): one bare `<loc>` URL per line, in file order; a
  sitemap index is followed into its sitemaps (same host only), gzip included;
- **an HTML index page** (`--html`, rungs 2, 4, 5): every link to the same host,
  in page order, once each, as `- [<link text>](<absolute url>)`.

Never pruned. The one filter is `--path-prefix`, keeping only items whose path
starts with it — a scope the operator approved, such as one language of a help
centre — and the header line says so. The raw index bytes are kept in
`_raw/index-<surface>-<date>/` with their sha256. An existing denominator for the
date stops it: a denominator is written once; a correction is a new dated file.

Permission and pacing come from `kbqa.fetch`, as for `kbqa capture`.
"""

import argparse
import gzip
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

from . import fetch
from .capture import _write_atomic, denominator_items

MD_LINK_RE = re.compile(r"\[[^\]]+\]\([^)\s]+\)")
SURFACES = ("product", "docs", "help")
MAX_SITEMAPS = 200
MAX_SECTIONS = 40


def _ranges(lines: List[int]) -> str:
    out, start, prev = [], None, None
    for n in lines:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return ",".join(out)


def sections(den: Path) -> List[Dict[str, object]]:
    """The denominator in a few lines: items grouped by host and the first path
    segments, with their line ranges — enough to propose a scope by line
    numbers without reading every item. Grouped by two segments, or by one when
    two would give more than MAX_SECTIONS groups."""
    items = denominator_items(den)
    for depth in (2, 1, 0):
        groups: Dict[str, List[int]] = {}
        for n, url in items:
            parts = urlsplit(url)
            segs = [x for x in parts.path.split("/") if x][:depth]
            key = parts.netloc + ("/" + "/".join(segs) if segs else "/")
            groups.setdefault(key, []).append(n)
        if len(groups) <= MAX_SECTIONS or depth == 0:
            return [{"section": k, "items": len(v), "lines": _ranges(v)} for k, v in groups.items()]
    return []


class _Links(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.links: List[Tuple[str, str]] = []
        self.href: Optional[str] = None
        self.text: List[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.skip += 1
        elif tag == "a" and not self.skip:
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self.href is not None:
            label = re.sub(r"\s+", " ", "".join(self.text)).strip()
            self.links.append((urljoin(self.base, self.href), label))
            self.href = None

    def handle_data(self, data):
        if self.href is not None and not self.skip:
            self.text.append(data)


def _strip_fragment(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


def _xml_locs(body: bytes) -> Tuple[str, List[str]]:
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    root = ET.fromstring(body)
    tag = root.tag.split("}")[-1]
    locs = [el.text.strip() for el in root.iter() if el.tag.split("}")[-1] == "loc" and el.text]
    return tag, locs


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa index")
    ap.add_argument("--out", required=True)
    ap.add_argument("--surface", required=True, choices=SURFACES)
    ap.add_argument("--rung", required=True, type=int, choices=range(1, 6))
    ap.add_argument("--url", required=True)
    ap.add_argument("--html", action="store_true", help="the index is an HTML page of links")
    ap.add_argument("--path-prefix", default=None)
    ap.add_argument("--date", default=None)
    args = ap.parse_args(argv)

    subject = Path(args.out)
    day = args.date or date.today().isoformat()
    s, url = args.surface, args.url
    den = subject / f"_denominator-{s}-{day}.md"
    raw_dir = subject / "_raw" / f"index-{s}-{day}"

    def finish(result: Dict, code: int) -> int:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    def refuse(msg: str, stop_line: Optional[str] = None) -> int:
        out = {"surface": s, "refused": msg}
        if stop_line:
            out["stop_lines_to_add"] = [stop_line]
        return finish(out, 1)

    if not subject.is_dir():
        return refuse(f"no subject folder {subject}")
    if den.exists() or raw_dir.exists():
        return refuse(f"{den.name} or _raw/{raw_dir.name}/ already exists — a denominator is written once")

    host = fetch.host_of(url)
    try:
        rb = fetch.robots_for(subject, host, day)
    except fetch.FetchError as exc:
        return refuse(str(exc))
    pacer = fetch.Pacer()

    def get(u: str):
        ok, rule = rb.check(u)
        if rb.site_wide_refused():
            return None, f"- {u} | refused: robots (surface {s})"
        if not ok:
            return None, f"- {u} | excluded: robots {rule} (surface {s})"
        pacer.wait(host, rb.crawl_delay())
        r = fetch.get(u)
        if r.status in fetch.THROTTLE_STATUSES:
            raise fetch.FetchError(f"HTTP {r.status} — throttled")
        if r.status != 200:
            raise fetch.FetchError(f"HTTP {r.status} from {u}")
        if fetch.host_of(r.url) != host:
            return None, f"- {u} | third-party host: {fetch.host_of(r.url)} (surface {s})"
        return r, None

    sources: List[Tuple[str, bytes, str]] = []  # (served url, bytes, content type)
    items: List[str] = []
    try:
        r, stop = get(url)
        if r is None:
            return refuse(f"the index {url} may not be fetched", stop)
        sources.append((r.url, r.body, r.content_type))
        ctype = r.content_type.split(";")[0].strip().lower()
        if args.html:
            parser = _Links(r.url)
            parser.feed(fetch.decode(r.body, r.content_type))
            seen = set()
            for href, label in parser.links:
                href = _strip_fragment(href)
                if not href.startswith(("http://", "https://")) or fetch.host_of(href) != host:
                    continue
                if href in seen or href == _strip_fragment(r.url):
                    continue
                seen.add(href)
                items.append(f"- [{label or href}]({href})")
        elif ctype.endswith("xml") or r.body.lstrip()[:5] in (b"<?xml", b"<urls", b"<site") or r.body[:2] == b"\x1f\x8b":
            tag, locs = _xml_locs(r.body)
            if tag == "sitemapindex":
                children = [c for c in locs if fetch.host_of(c) == host][:MAX_SITEMAPS]
                locs = []
                for child in children:
                    cr, cstop = get(child)
                    if cr is None:
                        return refuse(f"a sitemap of the index may not be fetched: {child}", cstop)
                    sources.append((cr.url, cr.body, cr.content_type))
                    locs += _xml_locs(cr.body)[1]
            items = [loc for loc in dict.fromkeys(locs)]
        else:
            text = fetch.decode(r.body, r.content_type)
            items = [ln.rstrip() for ln in text.splitlines() if MD_LINK_RE.search(ln)]
    except (fetch.FetchError, ET.ParseError, OSError) as exc:
        return refuse(f"the index could not be read: {exc}")

    note = ""
    if args.path_prefix:
        before = len(items)
        def path_ok(line: str) -> bool:
            m = re.search(r"\((https?://[^)\s]+)\)", line) or re.search(r"(https?://\S+)", line)
            return bool(m) and urlsplit(m.group(1)).path.startswith(args.path_prefix)
        items = [ln for ln in items if path_ok(ln)]
        note = f" · items whose path starts with {args.path_prefix} ({len(items)} of {before}; scope approved by the operator)"
    if not items:
        return refuse(f"the index at {url} holds no items" + (" under the path prefix" if note else ""))

    raw_dir.mkdir(parents=True)
    manifest = ["raw\tsha256\tbytes\tcontent_type\turl"]
    for n, (served, body, ctype) in enumerate(sources, start=1):
        name = f"{n:03d}.raw"
        _write_atomic(raw_dir / name, body)
        manifest.append(f"{name}\t{hashlib.sha256(body).hexdigest()}\t{len(body)}\t{ctype}\t{served}")
    _write_atomic(raw_dir / "MANIFEST.tsv", ("\n".join(manifest) + "\n").encode("utf-8"))
    header = f"Index: {s}, rung {args.rung} — {sources[0][0]}{note}"
    data = (header + "\n" + "\n".join(items) + "\n").encode("utf-8")
    _write_atomic(den, data)
    return finish({"surface": s, "denominator": str(den), "rung": args.rung, "items": len(items),
                   "sha256": hashlib.sha256(data).hexdigest(), "sources": [u for u, _, _ in sources],
                   "raw": f"_raw/{raw_dir.name}/", "sections": sections(den)}, 0)


def main() -> None:  # pragma: no cover
    sys.exit(run())
