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
`_raw/index-<surface>-<date>/` with their sha256. A denominator is written once
and never overwritten. A correction made the same day is `--supersede`: it
writes `_denominator-<surface>-<date>b.md` (then `c`, …), whose header names the
file it supersedes; the superseded file stays. Windows are cut from the current
denominator only — the latest by date, then by letter.

`sections` sums the denominator up for the plan: for an llms.txt, its own `##`
headings, each with the line ranges of its items; otherwise groups by host and
the first path segments.

`probe` is the plan's look at each host before scope is approved: one item of
each host that has a robots record from today gets one GET, its body never read
or kept. A 401 or 403 is flagged, with whether the page's own copy answers, so a
host that refuses our fetcher is seen at planning, not after twenty pages.

Permission and pacing come from `kbqa.fetch`, as for `kbqa capture`; G0 is run
first when today's robots record is missing.
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

from . import fetch, language, stops
from .capture import DENOMINATOR_RE, _write_atomic, denominator_items, denominators, site_copy_url

LANGUAGE_COPIES = "LANGUAGE-COPIES.tsv"
MD_LINK_RE = re.compile(r"\[[^\]]+\]\([^)\s]+\)")
H2_RE = re.compile(r"^##\s+(.+?)\s*#*\s*$")
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


def heading_sections(source_lines: List[str], kept: List[int]) -> List[Dict[str, object]]:
    """Sections from an llms.txt's own `##` headings: each heading with the
    denominator lines of the items under it. `kept[i]` is the denominator line
    of source line i, or 0 when that line is not an item."""
    groups: Dict[str, List[int]] = {}
    order: List[str] = []
    current = "(before the first ## heading)"
    for i, ln in enumerate(source_lines):
        m = H2_RE.match(ln)
        if m:
            current = m.group(1).strip()
            continue
        if kept[i]:
            if current not in groups:
                groups[current] = []
                order.append(current)
            groups[current].append(kept[i])
    return [{"section": k, "items": len(groups[k]), "lines": _ranges(groups[k])} for k in order]


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


def _xml_locs(body: bytes) -> Tuple[str, List[str], Dict[str, str]]:
    """(root tag, every <loc>, {page: its English alternate} from hreflang links)."""
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    root = ET.fromstring(body)
    tag = root.tag.split("}")[-1]
    locs = [el.text.strip() for el in root.iter() if el.tag.split("}")[-1] == "loc" and el.text]
    urls = [el for el in root.iter() if el.tag.split("}")[-1] == "url"]
    return tag, locs, language.english_alternates(urls)


def _item_url(line: str) -> str:
    m = re.search(r"\((https?://[^)\s]+)\)", line) or re.search(r"(https?://\S+)", line)
    return m.group(1) if m else ""


def _probe(subject: Path, day: str, den: Path, pacer: "fetch.Pacer",
           robots: Dict[str, "fetch.Robots"]) -> List[Dict[str, object]]:
    """One GET of one item per host that has today's robots record — the body
    never read — so a host refusing our fetcher is flagged before scope."""
    firsts: Dict[str, str] = {}
    for _, u in denominator_items(den):
        firsts.setdefault(fetch.host_of(u), u)
    out = []
    for host, u in firsts.items():
        if host not in robots:
            if not (subject / f"_robots-{host}-{day}.txt").exists():
                out.append({"host": host, "url": u, "probed": False,
                            "note": "no robots record from today: G0 has not run for this host, so it was not probed"})
                continue
            robots[host] = fetch.robots_for(subject, host, day)
        rb = robots[host]
        if rb.site_wide_refused() or not rb.check(u)[0]:
            out.append({"host": host, "url": u, "probed": False, "note": "robots closes this page to us"})
            continue
        pacer.wait(host, rb.crawl_delay())
        status, reason = fetch.probe(u)
        entry: Dict[str, object] = {"host": host, "url": u, "probed": True, "status": status}
        if status in (401, 403):
            copy = site_copy_url(u)
            copy_status = None
            if copy and fetch.host_of(copy) == host and rb.check(copy)[0]:
                pacer.wait(host, rb.crawl_delay())
                copy_status = fetch.probe(copy)[0]
            entry.update({"flag": f"refused: HTTP {status}", "site_copy": copy, "site_copy_status": copy_status,
                          "next_step": "operator",
                          "note": f"{host} refuses our fetcher although robots allows it. Decide before approving "
                                  "scope: its own copy (site_copy_status 200 means the capture can use it), "
                                  "supplied material, or a stop line for the surface."})
        elif status != 200:
            entry.update({"flag": reason or f"HTTP {status}", "next_step": "operator"})
        out.append(entry)
    return out


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa index")
    ap.add_argument("--out", required=True)
    ap.add_argument("--surface", required=True, choices=SURFACES)
    ap.add_argument("--rung", required=True, type=int, choices=range(1, 6))
    ap.add_argument("--url", required=True)
    ap.add_argument("--html", action="store_true", help="the index is an HTML page of links")
    ap.add_argument("--path-prefix", default=None)
    ap.add_argument("--supersede", action="store_true",
                    help="correct today's denominator: write <date>b.md (then c, …), naming what it supersedes")
    ap.add_argument("--all-languages", action="store_true",
                    help="keep every language copy (default: when English exists, it is enough)")
    ap.add_argument("--date", default=None)
    args = ap.parse_args(argv)

    subject = Path(args.out)
    day = args.date or date.today().isoformat()
    s, url = args.surface, args.url

    def finish(result: Dict, code: int) -> int:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    def refuse(msg: str, stop_line: Optional[str] = None, **extra) -> int:
        out = {"surface": s, "refused": msg, "next_step": "operator", **extra}
        if stop_line:
            out["stop_lines_to_add"] = [stop_line]
            out["next_step"] = f"stop: {stop_line}"
        return finish(out, 1)

    if not subject.is_dir():
        return refuse(f"no subject folder {subject}")
    todays = [p for p in denominators(subject, s) if DENOMINATOR_RE.match(p.name).group("date") == day]
    supersedes = None
    if args.supersede:
        if not todays:
            return refuse(f"no denominator of {s} dated {day} to supersede; a denominator of a new day "
                          "needs no --supersede")
        supersedes = todays[-1]
        fix = DENOMINATOR_RE.match(supersedes.name).group("fix")
        letter = chr(ord(fix) + 1) if fix else "b"
        if letter > "z":
            return refuse(f"no correction letter is left for {s} on {day}")
        name = f"{s}-{day}{letter}"
    elif todays:
        return refuse(f"{todays[-1].name} already exists — a denominator is written once. A correction the "
                      "same day is --supersede, with the operator's word: it writes a new file and keeps this one")
    else:
        name = f"{s}-{day}"
    den = subject / f"_denominator-{name}.md"
    raw_dir = subject / "_raw" / f"index-{name}"
    if den.exists() or raw_dir.exists():
        return refuse(f"{den.name} or _raw/{raw_dir.name}/ already exists — a denominator is written once")

    host = fetch.host_of(url)
    permission: List[Dict[str, object]] = []
    try:
        rb, ran = fetch.ensure_robots(subject, host, day)
    except fetch.FetchError as exc:
        return refuse(str(exc))
    if ran:
        permission.append(ran)
    pacer = fetch.Pacer()

    def stopline(u: str, reason: str) -> str:
        ln, err = stops.try_line(u, reason, s)
        if ln is None:  # fetched data the vocabulary cannot read: the operator's, never a crash
            raise fetch.FetchError(f"{u}: {reason} — its stop line is not in the vocabulary ({err})")
        return ln

    def get(u: str):
        ok, rule = rb.check(u)
        if rb.site_wide_refused():
            return None, stopline(u, "refused: robots")
        if not ok:
            return None, stopline(u, f"excluded: robots {rule}")
        pacer.wait(host, rb.crawl_delay())
        r = fetch.get(u)
        if r.status in fetch.THROTTLE_STATUSES:
            raise fetch.FetchError(f"HTTP {r.status} — throttled")
        if r.status in (401, 403):
            raise Refused(u, r.status)
        if r.status != 200:
            raise fetch.FetchError(f"HTTP {r.status} from {u}")
        if fetch.host_of(r.url) != host:
            return None, stopline(u, f"third-party host: {fetch.host_of(r.url)}")
        return r, None

    sources: List[Tuple[str, bytes, str]] = []  # (served url, bytes, content type)
    items: List[str] = []
    heads: Optional[Tuple[List[str], List[bool]]] = None  # llms.txt lines, and which are items
    hreflang: Dict[str, str] = {}  # page -> its English alternate, as the sitemap states
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
            tag, locs, alt = _xml_locs(r.body)
            hreflang.update(alt)
            if tag == "sitemapindex":
                children = [c for c in locs if fetch.host_of(c) == host][:MAX_SITEMAPS]
                locs = []
                for child in children:
                    cr, cstop = get(child)
                    if cr is None:
                        return refuse(f"a sitemap of the index may not be fetched: {child}", cstop)
                    sources.append((cr.url, cr.body, cr.content_type))
                    _, child_locs, alt = _xml_locs(cr.body)
                    locs += child_locs
                    hreflang.update(alt)
            items = [loc for loc in dict.fromkeys(locs)]
        else:
            text = fetch.decode(r.body, r.content_type)
            src = [ln.rstrip() for ln in text.splitlines()]
            is_item = [bool(MD_LINK_RE.search(ln)) for ln in src]
            items = [ln for ln, it in zip(src, is_item) if it]
            heads = (src, is_item)
    except Refused as exc:
        line = stops.try_line(exc.url, f"refused: HTTP {exc.status}", s)[0]
        return refuse(f"the index could not be read: HTTP {exc.status} from {exc.url} — the host refuses our "
                      "fetcher although robots allows it", suggested_stop_line=line,
                      options=["the operator supplies the material", "approve the suggested stop line",
                               "another rung of the surface's index"])
    except (fetch.FetchError, ET.ParseError, OSError) as exc:
        return refuse(f"the index could not be read: {exc}")

    note = ""
    all_items = items  # `keep` stays aligned with these, for the llms.txt sections
    keep = [True] * len(all_items)
    if args.path_prefix:
        def path_ok(line: str) -> bool:
            u = _item_url(line)
            return bool(u) and urlsplit(u).path.startswith(args.path_prefix)
        keep = [path_ok(ln) for ln in all_items]
        note = (f" · items whose path starts with {args.path_prefix} ({sum(keep)} of {len(all_items)}; "
                "scope approved by the operator)")
    # English is enough (the operator, 2026-10-22): a language copy of a page the
    # index also lists in English is left out, and listed with that page.
    lang_copies: Dict[str, str] = {}
    if not args.all_languages:
        lang_copies = language.copies((_item_url(ln) for ln, k in zip(all_items, keep) if k), hreflang)
        if lang_copies:
            before = sum(keep)
            keep = [k and _item_url(ln) not in lang_copies for ln, k in zip(all_items, keep)]
            note += (f" · {before - sum(keep)} language copies left out, each with its English page in "
                     f"_raw/index-{name}/{LANGUAGE_COPIES} (English is enough: operator 2026-10-22)")
    items = [ln for ln, k in zip(all_items, keep) if k]
    if not items:
        return refuse(f"the index at {url} holds no items" + (" under the path prefix" if note else ""))
    if supersedes is not None:
        note += f" · supersedes {supersedes.name}"

    raw_dir.mkdir(parents=True)
    manifest = ["raw\tsha256\tbytes\tcontent_type\turl"]
    for n, (served, body, ctype) in enumerate(sources, start=1):
        name_ = f"{n:03d}.raw"
        _write_atomic(raw_dir / name_, body)
        manifest.append(f"{name_}\t{hashlib.sha256(body).hexdigest()}\t{len(body)}\t{ctype}\t{served}")
    _write_atomic(raw_dir / "MANIFEST.tsv", ("\n".join(manifest) + "\n").encode("utf-8"))
    if lang_copies:
        tsv = ["language_copy\tenglish_page"] + [f"{c}\t{e}" for c, e in sorted(lang_copies.items())]
        _write_atomic(raw_dir / LANGUAGE_COPIES, ("\n".join(tsv) + "\n").encode("utf-8"))
    header = f"Index: {s}, rung {args.rung} — {sources[0][0]}{note}"
    data = (header + "\n" + "\n".join(items) + "\n").encode("utf-8")
    _write_atomic(den, data)

    if heads is not None and any(H2_RE.match(ln) for ln in heads[0]):
        # denominator line of each kept source item: line 1 is the header
        kept, k, line_no = [], iter(keep), 1
        for is_item in heads[1]:
            if is_item and next(k):
                line_no += 1
                kept.append(line_no)
            else:
                kept.append(0)
        secs, by = heading_sections(heads[0], kept), "## headings"
    else:
        secs, by = sections(den), "host and path"
    result = {"surface": s, "denominator": str(den), "rung": args.rung, "items": len(items),
              "sha256": hashlib.sha256(data).hexdigest(), "sources": [u for u, _, _ in sources],
              "raw": f"_raw/{raw_dir.name}/", "sections_by": by, "sections": secs,
              "probe": _probe(subject, day, den, pacer, {host: rb}), "permission": permission}
    if supersedes is not None:
        result["supersedes"] = supersedes.name
    if lang_copies:
        result["language_copies"] = {"left_out": len(lang_copies), "file": f"_raw/{raw_dir.name}/{LANGUAGE_COPIES}"}
    return finish(result, 0)


class Refused(fetch.FetchError):
    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status} from {url}")
        self.url, self.status = url, status


def main() -> None:  # pragma: no cover
    sys.exit(run())
