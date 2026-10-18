"""kbqa capture — one window of pages, verbatim and reproducible, sized by code.

    python3 -m kbqa capture --out <subject dir> --surface <s>
        --denominator <file> [--select <lines> | --select-prefix <path>...] [--offset <n>]
        [--max-pages <n>] [--max-chars <n>]
    python3 -m kbqa capture --out <d> --surface <s> --denominator <file> --resume
    python3 -m kbqa capture --out <d> --surface <s> --retry-failed
    python3 -m kbqa capture --out <d> --surface <s> --status [--files]
    python3 -m kbqa capture --out <d> --batch <b> --url <url>... | --urls-file <f>

**The window is sliced by code.** Given the surface's denominator, the
operator-approved selection of its items — by line (`--select 6,22-23,88-101`),
by path (`--select-prefix /hc/en-us/`, repeatable), or all items when neither
is given — and the offset into that selection, it takes items in order until
`--max-pages` pages were attempted or the captured text passed `--max-chars`.
The agent never reads the denominator, and never decides when a window is
"too large": the receipt says `window_end` — `exhausted` only when no selected
item remains — with `next_offset` for the next window. The denominator stays
complete; a selection only says which of its items this surface's windows take.

For each URL, in order: permission from today's robots record (`kbqa.fetch`;
G0 is run first when there is none), the host's crawl delay, then the raw
bytes. Each page's bytes are kept unedited in `_raw/<batch>/` with their sha256
(`MANIFEST.tsv`), and the page's text — `kbqa.htmltext`, the same rendering
every time — goes into `_capture-<batch>.raw.txt` between
`=====BEGIN <url>=====` / `=====END <url>=====` markers. The receipt gives each
page's line range in the capture, so the row-writer reads one page at a time.

**The receipt is a file**, `_raw/<batch>/RECEIPT.json`, beside the window's
state (`WINDOW.json`), and the same JSON is printed. The row-writer reads it
from disk, so no agent retypes window fields between the capture and the rows.
Beside it, `_raw/<batch>/FEATURES.md` lists the subject's features as they
stand before this batch (`kbqa.features`): the row-writer reads it to tell a
new feature from another source of one it already has (`same_feature_as`).

**Every failure carries its next step**, decided here, never by an agent:
`retry` (a later run, `--resume` or `--retry-failed`), `operator` (with a
suggested stop line where one fits), or `stop: <exact line>`. A host that
refuses our fetcher (HTTP 401 or 403) or a page that shows no text without
JavaScript is tried once more through the site's own copy (`site-copy`): the
page's markdown twin at the same URL with `.md` added (`index.html.md` for a
path ending in `/`), the llms.txt convention. The copy is used only when it is
on the same host, robots allows it, and it is served as text; the capture keys
it by the page's own URL and the receipt says `fetch_method: site-copy`.

Batch dates follow the access date: a surface collected across midnight goes
on in batches of the new date (`…-10-17-w07` → `…-10-18-w01`); its windows
still chain, because the chain is read from the windows' state, not their names.

It never overwrites: an existing capture or raw folder stops it. It exits 0 if
at least one page was captured, 1 otherwise. A 429 or 503 ends the window there
(`stopped: throttled`).
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from . import __version__, fetch, features, stops
from .htmltext import render, visible_chars

BATCH_RE = re.compile(r"^(product|docs|help)-\d{4}-\d{2}-\d{2}-w\d{2}$")
MARKER_RE = re.compile(r"^=====(BEGIN|END) ")
MD_LINK_URL_RE = re.compile(r"\[[^\]]+\]\((?P<url>[^)\s]+)\)")
BARE_URL_RE = re.compile(r"^\s*(?P<url>https?://\S+)\s*$")
DENOMINATOR_RE = re.compile(
    r"^_denominator-(?P<surface>product|docs|help)-(?P<date>\d{4}-\d{2}-\d{2})(?P<fix>[b-z]?)\.md$")
# A JavaScript shell: a page with scripts and almost no text, or little text
# around an app mount point. A short page that is simply short is not a shell.
JS_EMPTY_CHARS = 50
JS_SHELL_CHARS = 200
MOUNT_RE = re.compile(r"""<div[^>]+id=["'](root|app|__next|__nuxt|svelte)["']""", re.I)
TEXT_TYPES = ("text/plain", "text/markdown", "text/x-markdown")
MAX_PAGES = 20
MAX_CHARS = 150_000
# A page is read in parts no larger than this; each part keeps its context.
PART_CHARS = 20_000
OVERLAP_LINES = 3      # lines of the previous part repeated for context …
OVERLAP_SHARE = 0.10   # … but never more than a tenth of a part
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
REFUSED_STATUSES = (401, 403)
# A host is suggested closed for the surface only when it refused this many
# pages of one window and served none: one refusal is a page, not a host.
HOST_REFUSAL_PAGES = 3


def parts_of(lines: List[str], headings: List[Tuple[int, int, str]],
             breadcrumb: Optional[int], part_chars: int = PART_CHARS) -> List[Dict[str, object]]:
    """Split one page's text lines into parts for reading — at headings where
    possible, at line ends otherwise, never inside a line.

    Each part says which lines are its own (rows come only from those), where to
    start reading so a few lines of the previous part give context, and the
    context that is not in its lines: the page's breadcrumb and the headings it
    sits under. Indexes are 0-based into `lines`.
    """
    head_at = {i: (lvl, txt) for i, lvl, txt in headings}
    parts, start, size = [], 0, 0
    last_head = None  # the latest heading line after `start`: the preferred cut
    for i, ln in enumerate(lines):
        add = len(ln) + 1
        if size and size + add > part_chars and i > start:
            cut = last_head if last_head is not None and last_head > start else i
            parts.append((start, cut - 1))
            start, size = cut, sum(len(x) + 1 for x in lines[cut:i])
            last_head = None
        if i in head_at and i > start:
            last_head = i
        size += add
    if lines:
        parts.append((start, len(lines) - 1))
    out = []
    for a, b in parts:
        stack: List[Tuple[int, str]] = []
        for i in sorted(head_at):
            if i >= a:
                break
            lvl, txt = head_at[i]
            stack = [h for h in stack if h[0] < lvl] + [(lvl, txt)]
        if a in head_at:  # a part that opens on a heading sits under that heading's parents only
            stack = [h for h in stack if h[0] < head_at[a][0]]
        read_from = a
        budget = int(part_chars * OVERLAP_SHARE)
        while read_from > 0 and a - read_from < OVERLAP_LINES and \
                sum(len(x) + 1 for x in lines[read_from - 1:a]) <= budget:
            read_from -= 1
        out.append({"own": [a, b], "read_from": read_from,
                    "breadcrumb": lines[breadcrumb] if breadcrumb is not None else None,
                    "headings": [t for _, t in stack]})
    return out


def _kind(content_type: str) -> Optional[str]:
    ct = content_type.split(";")[0].strip().lower()
    if ct in ("text/html", "application/xhtml+xml"):
        return "html"
    if ct in TEXT_TYPES:
        return "text"
    return None


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def denominator_items(path: Path) -> List[Tuple[int, str]]:
    """(line number, URL) for every item line, the shapes /kbqa-check reads."""
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if n == 1 and line.startswith("Index:"):
            continue
        m = MD_LINK_URL_RE.search(line) or BARE_URL_RE.match(line)
        if m:
            out.append((n, m.group("url").strip()))
    return out


def denominators(subject: Path, surface: str) -> List[Path]:
    """A surface's denominators, oldest first: by date, then by correction
    letter (`…-2026-10-17.md` before `…-2026-10-17b.md`). The last is current."""
    found = []
    for p in subject.iterdir() if subject.is_dir() else []:
        m = DENOMINATOR_RE.match(p.name)
        if m and m.group("surface") == surface and p.is_file():
            found.append(((m.group("date"), m.group("fix")), p))
    return [p for _, p in sorted(found)]


def current_denominator(subject: Path, surface: str) -> Optional[Path]:
    dens = denominators(subject, surface)
    return dens[-1] if dens else None


def parse_select(spec: str) -> List[int]:
    """`6,22-23,88-101` → [6, 22, 23, 88, …, 101], in the order written."""
    lines: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            if hi < lo:
                raise ValueError(f"range {part!r} runs backwards")
            lines.extend(range(lo, hi + 1))
        else:
            lines.append(int(part))
    return lines


STATE = "WINDOW.json"
RECEIPT = "RECEIPT.json"
FEATURES = "FEATURES.md"  # the subject's anchors, for the row-writer's same_feature_as
RETRY_RUNS = 3  # a page that keeps failing is retried in at most this many runs


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _windows(subject: Path, surface: str) -> List[Dict]:
    """Every window recorded for a surface, in batch order — the resume state,
    on disk, never in a session's memory."""
    out = []
    raw = subject / "_raw"
    if not raw.is_dir():
        return out
    for d in sorted(raw.iterdir()):
        f = d / STATE
        if d.is_dir() and f.exists():
            st = json.loads(f.read_text(encoding="utf-8"))
            if st.get("surface") == surface:
                out.append(st)
    return out


def _free_batch(subject: Path, surface: str, day: str) -> str:
    for n in range(1, 100):
        b = f"{surface}-{day}-w{n:02d}"
        if not ((subject / f"_capture-{b}.raw.txt").exists()
                or (subject / f"_collect-{b}-staging.md").exists()
                or (subject / "_raw" / b).exists()):
            return b
    raise ValueError(f"no free batch number left for {surface} on {day}")


def _stopped_urls(subject: Path) -> set:
    f = subject / stops.STOPS_NAME
    if not f.exists():
        return set()
    from .gates.g4_completeness import stopped_urls
    return stopped_urls(f)


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def suggested_line(url: str, reason: str, runs: int = 1) -> Optional[str]:
    """The stop line the operator is asked to approve for a page no attempt
    could fetch — from the vocabulary, never typed by an agent."""
    base = _one_line(reason.split(" — ")[0])
    m = re.match(r"^HTTP (401|403)$", base)
    if m:
        return stops.try_line(url, f"refused: HTTP {m.group(1)}")[0]
    if base.startswith("content type application/pdf"):
        return stops.try_line(url, "not approved: pdf")[0]
    if base.startswith(("content type ", "the page's text contains")) or "not in the vocabulary" in base:
        return None  # not a fetch failure: the operator rules on what the page is
    return stops.try_line(url, f"unreachable: {base}" + (f" in {runs} runs" if runs > 1 else ""))[0]


OPTIONS = {
    "refused": ["the operator supplies the material", "approve the suggested stop line",
                "the rendered route, once the operator has chosen its browser tool"],
    "unreachable": ["approve the suggested stop line", "the operator opens the URL and rules on it"],
    "tls": ["the operator runs kbqa under a Python with a newer TLS", "approve the suggested stop line"],
    "throttled": ["retry later with a longer delay", "approve the suggested stop line"],
    "other": ["the operator opens the URL and rules on it"],
}


def _options(reason: str, cls: str) -> List[str]:
    if re.match(r"^HTTP (401|403)\b", reason):
        return OPTIONS["refused"]
    if reason.startswith("TLS:"):
        return OPTIONS["tls"]
    if cls == "throttled":
        return OPTIONS["throttled"]
    if suggested_line("https://x.test/", reason) is None:
        return OPTIONS["other"]
    return OPTIONS["unreachable"]


def _for_operator(url: str, reason: str, cls: str, runs: int) -> Dict[str, object]:
    return {"url": url, "reason": reason, "runs": runs, "next_step": "operator",
            "suggested_stop_line": suggested_line(url, reason, runs),
            "options": _options(reason, cls)}


def _retry_state(subject: Path, windows: List[Dict]):
    """Failed pages not captured or stopped since: (retryable, given up)."""
    captured = {u for w in windows for u in w.get("pages", [])}
    stopped = _stopped_urls(subject)
    runs: Dict[str, int] = {}
    last: Dict[str, Dict] = {}
    finals: Dict[str, Dict] = {}
    for w in windows:
        for f in w.get("failures", []):
            if f.get("class") in ("transient", "throttled"):
                runs[f["url"]] = runs.get(f["url"], 0) + 1
                last[f["url"]] = f
            elif f.get("class") in ("final", "unsupported"):
                finals[f["url"]] = f
    retryable, given_up = [], []
    for url, n in runs.items():
        if url in captured or url in stopped:
            continue
        if n >= RETRY_RUNS:
            given_up.append(_for_operator(url, last[url]["reason"], last[url]["class"], n))
        else:
            retryable.append(url)
    for url, f in finals.items():
        if url not in captured and url not in stopped:
            given_up.append(_for_operator(url, f["reason"], "final", 1))
    return retryable, given_up


SUBJECT_FILES = ("_stop-conditions.md",)


def _files(subject: Path, surface: str) -> Dict[str, List[Dict[str, object]]]:
    """A read-only inventory of what is on disk for a surface, with sizes."""
    def entry(p: Path) -> Dict[str, object]:
        return {"name": p.name, "bytes": p.stat().st_size}
    names = sorted(p for p in subject.iterdir() if p.is_file())
    out: Dict[str, List[Dict[str, object]]] = {
        "denominators": [entry(p) for p in denominators(subject, surface)],
        "captures": [entry(p) for p in names if p.name.startswith(f"_capture-{surface}-")],
        "staging": [entry(p) for p in names if p.name.startswith(f"_collect-{surface}-")],
        "maps": [entry(p) for p in names if p.name.startswith(f"_map-{surface}-")],
        "robots_records": [entry(p) for p in names if p.name.startswith("_robots-")],
        "subject": [entry(subject / n) for n in SUBJECT_FILES if (subject / n).is_file()],
        "receipts": [],
    }
    raw = subject / "_raw"
    if raw.is_dir():
        for d in sorted(raw.iterdir()):
            if d.is_dir() and d.name.startswith(f"{surface}-") and (d / RECEIPT).is_file():
                out["receipts"].append({"name": f"_raw/{d.name}/{RECEIPT}", "bytes": (d / RECEIPT).stat().st_size})
    return out


def _chain(windows: List[Dict], den_name: Optional[str]) -> List[Dict]:
    """The windows a surface resumes from: those cut from its current
    denominator. Windows of a superseded denominator are kept, never followed."""
    return [w for w in windows if w.get("kind") == "window" and w.get("denominator")
            and (den_name is None or w.get("denominator") == den_name)]


def _status(subject: Path, surface: str, files: bool) -> int:
    windows = _windows(subject, surface)
    current = current_denominator(subject, surface)
    chain = _chain(windows, current.name if current else None)
    retryable, given_up = _retry_state(subject, windows)
    out = {"surface": surface, "current_denominator": current.name if current else None,
           "windows": [
               {k: w.get(k) for k in ("batch", "kind", "access_date", "denominator", "select", "select_prefix",
                                       "offset", "next_offset", "remaining", "window_end")} for w in windows],
           "resume_from": chain[-1]["next_offset"] if chain else 0,
           "exhausted": bool(chain) and chain[-1].get("window_end") == "exhausted",
           "retryable_failed_pages": retryable, "needs_operator": given_up}
    if files:
        out["files"] = _files(subject, surface)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def site_copy_url(url: str) -> Optional[str]:
    """The page's markdown twin, by the llms.txt convention: the same URL with
    `.md` added, or `index.html.md` for a path ending in `/`. None when the URL
    has a query, or already names a markdown or text file."""
    p = urlsplit(url)
    if p.query or p.path.lower().endswith((".md", ".txt")):
        return None
    base = url.split("#", 1)[0]
    return base + ("index.html.md" if base.endswith("/") or not p.path else ".md")


def _selection_by_prefix(items: List[Tuple[int, str]], prefixes: List[str]) -> List[str]:
    return [u for _, u in items if any(urlsplit(u).path.startswith(px) for px in prefixes)]


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa capture")
    ap.add_argument("--out", required=True, help="the subject folder")
    ap.add_argument("--surface", choices=("product", "docs", "help"),
                    help="name the next free batch of this surface for today")
    ap.add_argument("--batch", help="an explicit batch name (tests; the fetcher uses --surface)")
    ap.add_argument("--denominator", help="the surface's denominator; the window is sliced from it")
    ap.add_argument("--select", help="the approved denominator lines, e.g. 6,22-23,88-101")
    ap.add_argument("--select-prefix", action="append", default=[],
                    help="the approved items whose URL path starts with this (repeatable)")
    ap.add_argument("--offset", type=int, default=None, help="where in the selection this window begins")
    ap.add_argument("--resume", action="store_true", help="begin where the surface's recorded windows stopped")
    ap.add_argument("--retry-failed", action="store_true", help="retry pages that failed in earlier windows")
    ap.add_argument("--status", action="store_true", help="report the surface's recorded windows; fetch nothing")
    ap.add_argument("--files", action="store_true", help="with --status: the surface's files on disk, with sizes")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    ap.add_argument("--part-chars", type=int, default=PART_CHARS)
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--urls-file")
    ap.add_argument("--date", default=None, help="access date (tests)")
    args = ap.parse_args(argv)

    subject = Path(args.out)
    day = args.date or date.today().isoformat()
    b = args.batch or ""

    def refuse(msg: str, **extra) -> int:
        print(json.dumps({"batch": b or None, "refused": msg, "next_step": "operator", **extra},
                         ensure_ascii=False, indent=2))
        return 1

    if not subject.is_dir():
        return refuse(f"no subject folder {subject}")
    surface = args.surface or (b.split("-", 1)[0] if b else None)
    if surface not in ("product", "docs", "help"):
        return refuse("give --surface (or a batch name that starts with one)")
    if args.files and not args.status:
        return refuse("--files is read with --status only")
    if args.status:
        return _status(subject, surface, args.files)
    if not b:
        try:
            b = _free_batch(subject, surface, day)
        except ValueError as exc:
            return refuse(str(exc))
    if not BATCH_RE.match(b):
        return refuse(f"batch {b!r} is not <surface>-<YYYY-MM-DD>-wNN")
    if b.split("-", 1)[1][:10] != day:
        return refuse(f"batch {b!r} is not dated with today's access date {day}")
    capture = subject / f"_capture-{b}.raw.txt"
    raw_dir = subject / "_raw" / b
    if capture.exists() or raw_dir.exists():
        return refuse(f"{capture.name} or _raw/{b}/ already exists — a batch name is never reused")
    if args.select and args.select_prefix:
        return refuse("give --select or --select-prefix, not both")

    kind = "window"
    selection: List[str] = []
    den_sha = None
    select_spec = args.select or "all"
    prefixes: List[str] = list(args.select_prefix)
    offset = args.offset or 0
    needs_operator: List[Dict] = []
    if args.retry_failed:
        if args.denominator or args.url or args.urls_file or args.resume:
            return refuse("--retry-failed takes no other source")
        kind = "retry"
        windows = _windows(subject, surface)
        candidates, needs_operator = _retry_state(subject, windows)
        if not candidates:
            return refuse("no failed page is left to retry", needs_operator=needs_operator)
    elif args.denominator:
        if args.url or args.urls_file:
            return refuse("give either --denominator or --url/--urls-file, not both")
        den = Path(args.denominator)
        if not den.exists():
            return refuse(f"no denominator {den}")
        dm = DENOMINATOR_RE.match(den.name)
        current = current_denominator(den.parent, surface) if dm and dm.group("surface") == surface else None
        if current is not None and current.name != den.name:
            return refuse(f"{den.name} is superseded by {current.name}; windows are cut from the current "
                          "denominator only")
        den_sha = _sha(den)
        if args.resume:
            chain = _chain(_windows(subject, surface), den.name)
            if not chain:
                return refuse(f"nothing to resume: no window cut from {den.name} is recorded")
            for w in chain:
                if w["denominator_sha256"] != den_sha:
                    return refuse(f"window {w['batch']} was cut from another denominator ({w['denominator']} "
                                  f"as it was then) — {den.name} has changed since; resuming would point at "
                                  "other items")
                if w["select"] != (args.select or chain[0]["select"]):
                    return refuse(f"window {w['batch']} used the selection {w['select']!r}, "
                                  f"not {args.select!r} — scope would drift")
                if w.get("select_prefix", []) != (prefixes or chain[0].get("select_prefix", [])):
                    return refuse(f"window {w['batch']} used the path selection {w.get('select_prefix', [])!r}, "
                                  f"not {prefixes!r} — scope would drift")
            if chain[0]["offset"] != 0:
                return refuse(f"the first recorded window {chain[0]['batch']} does not start at 0")
            for prev, nxt in zip(chain, chain[1:]):
                if nxt["offset"] != prev["next_offset"]:
                    return refuse(f"windows {prev['batch']} and {nxt['batch']} leave a gap or overlap "
                                  f"({prev['next_offset']} → {nxt['offset']})")
            if chain[-1]["window_end"] == "exhausted":
                return refuse("the selection is exhausted: every selected item was attempted")
            select_spec = chain[0]["select"]
            prefixes = list(chain[0].get("select_prefix", []))
            offset = chain[-1]["next_offset"]
        items = denominator_items(den)
        by_line = dict(items)
        if prefixes:
            selection = _selection_by_prefix(items, prefixes)
            if not selection:
                return refuse(f"--select-prefix {prefixes!r} matches no item of {den.name}")
        elif select_spec != "all":
            try:
                wanted = parse_select(select_spec)
            except ValueError as exc:
                return refuse(f"--select: {exc}")
            missing = [n for n in wanted if n not in by_line]
            if missing:
                return refuse(f"--select names lines that hold no item: {missing[:10]}")
            selection = [by_line[n] for n in wanted]
        else:
            selection = list(by_line.values())
        selection = list(dict.fromkeys(selection))
        if not 0 <= offset <= len(selection):
            return refuse(f"offset {offset} is outside the selection of {len(selection)} items")
        candidates = selection[offset:]
        if not candidates:
            return refuse("no items to capture — the selection is exhausted")
    else:
        urls: List[str] = list(args.url)
        if args.urls_file:
            urls += [ln.strip() for ln in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
        candidates = list(dict.fromkeys(urls))  # in order, once each
        if not candidates:
            return refuse("no items to capture")

    robots: Dict[str, fetch.Robots] = {}
    permission: List[Dict[str, object]] = []
    pacer = fetch.Pacer()
    pages, failures, excluded, redirects, stop_lines = [], [], [], [], []
    blocks: List[str] = []
    raws: List[tuple] = []
    stopped = None
    attempted = 0
    chars = 0
    by_host: Dict[str, Dict[str, list]] = {}

    def host_tally(host: str) -> Dict[str, list]:
        return by_host.setdefault(host, {"attempted": [], "refused": [], "captured": []})

    def fail(url: str, reason: str, cls: str, attempts: int = 1, next_step: Optional[str] = None,
             tried: Optional[List[str]] = None) -> None:
        if next_step is None:
            next_step = "retry" if cls in ("transient", "throttled") else "operator"
        rec = {"url": url, "reason": reason, "class": cls, "attempts": attempts, "next_step": next_step}
        if tried:
            rec["tried"] = tried
        failures.append(rec)
        if cls == "final":
            needs_operator.append(_for_operator(url, reason, cls, 1))

    def stop_here(url: str, reason: str, cls: str, key: str, stop_reason: str,
                  tried: Optional[List[str]] = None) -> None:
        line, err = stops.try_line(key, stop_reason)
        if line is None:  # fetched data the vocabulary cannot read: the operator's, never a crash
            fail(url, f"{reason}; its stop line is not in the vocabulary ({err})", "final", tried=tried)
            return
        fail(url, reason, cls, next_step=f"stop: {line}", tried=tried)
        stop_lines.append(line)

    def robots_of(host: str) -> fetch.Robots:
        if host not in robots:
            rb, ran = fetch.ensure_robots(subject, host, day)
            robots[host] = rb
            if ran:
                permission.append(ran)
        return robots[host]

    def try_site_copy(url: str, host: str, rb: fetch.Robots):
        """(response, copy url) when the site's own copy serves the page as text."""
        copy = site_copy_url(url)
        if copy is None or fetch.host_of(copy) != host or not rb.check(copy)[0]:
            return None, copy
        pacer.wait(host, rb.crawl_delay())
        r, cls, _, _ = fetch.get_patiently(copy)
        if cls != "ok" or r is None or fetch.host_of(r.url) != host or _kind(r.content_type) != "text":
            return None, copy
        head = r.body.lstrip()[:15].lower()
        if head.startswith((b"<!doctype", b"<html")):
            return None, copy  # an HTML page served as text: not a copy
        if visible_chars(fetch.decode(r.body, r.content_type)) < JS_EMPTY_CHARS:
            return None, copy
        return r, copy

    def keep(url: str, r, method: str, text_in: str, page_kind: str, copy_of: Optional[str] = None) -> bool:
        nonlocal chars
        if page_kind == "html":
            rendered = render(text_in)
            text, heads, crumb = rendered.text, rendered.headings, rendered.breadcrumb
        else:
            text = text_in.replace("\r\n", "\n").rstrip("\n")
            heads = [(j, len(m.group(1)), m.group(2)) for j, ln in enumerate(text.split("\n"))
                     if (m := MD_HEADING_RE.match(ln))]
            crumb = None
        if any(MARKER_RE.match(ln) for ln in text.splitlines()):
            fail(url, "the page's text contains a capture marker line", "unsupported")
            needs_operator.append(_for_operator(url, failures[-1]["reason"], "unsupported", 1))
            return False
        key = copy_of or r.url  # a copy is keyed by the page it is a copy of
        if key != url:
            redirects.append({"requested": url, "served": r.url})
        n = len(raws) + 1
        ext = "html" if page_kind == "html" else "txt"
        raw_name = f"{n:03d}.{ext}"
        raw_sha = hashlib.sha256(r.body).hexdigest()
        raws.append((raw_name, r.body, r.url, raw_sha, r.content_type))
        blocks.append(f"=====BEGIN {key}=====\n{text}\n=====END {key}=====\n")
        chars += len(text)
        page = {"url": key, "requested": url, "fetch_method": method, "status": r.status,
                "content_type": r.content_type, "bytes": len(r.body),
                "raw": f"_raw/{b}/{raw_name}", "raw_sha256": raw_sha,
                "text_chars": visible_chars(text), "oversize": len(text) > args.max_chars,
                "_parts": parts_of(text.split("\n"), heads, crumb, args.part_chars)}
        if copy_of:
            page["served_by"] = r.url
        pages.append(page)
        return True

    for i, url in enumerate(candidates):
        if attempted >= args.max_pages:
            stopped = {"reason": "budget: max-pages"}
            break
        if blocks and chars >= args.max_chars:
            stopped = {"reason": "budget: max-chars"}
            break
        attempted += 1
        host = fetch.host_of(url)
        try:
            rb = robots_of(host)
        except fetch.FetchError as exc:
            return refuse(str(exc), permission=permission)
        if rb.site_wide_refused():
            stop_here(url, "refused: robots (site-wide)", "refused", url, "refused: robots")
            continue
        ok, rule = rb.check(url)
        if not ok:
            line, err = stops.try_line(url, f"excluded: robots {rule}")
            if line is None:
                excluded.append({"url": url, "rule": rule, "next_step": "operator", "note": err})
                needs_operator.append({"url": url, "reason": f"excluded by robots rule {rule!r}; {err}",
                                       "runs": 1, "next_step": "operator", "suggested_stop_line": None,
                                       "options": OPTIONS["other"]})
                continue
            excluded.append({"url": url, "rule": rule, "next_step": f"stop: {line}"})
            stop_lines.append(line)
            continue
        host_tally(host)["attempted"].append(url)
        pacer.wait(host, rb.crawl_delay())
        r, cls, tries, reason = fetch.get_patiently(url)
        if cls == "throttled":
            fail(url, f"{reason} — throttled; window ended here", "throttled", tries)
            attempted -= 1  # not taken: the next window starts again at this item
            host_tally(host)["attempted"].pop()
            stopped = {"reason": "throttled", "not_attempted": candidates[i:]}
            break
        if cls != "ok" and r is not None and r.status in REFUSED_STATUSES:
            copy, copy_url = try_site_copy(url, host, rb)
            if copy is not None and keep(url, copy, "site-copy", fetch.decode(copy.body, copy.content_type),
                                         "text", copy_of=url):
                host_tally(host)["captured"].append(url)
                continue
            fail(url, reason, cls, tries, tried=["direct", f"site-copy {copy_url}" if copy_url else "site-copy: none"])
            host_tally(host)["refused"].append(url)
            continue
        if cls != "ok":
            fail(url, reason, cls, tries)
            continue
        if fetch.host_of(r.url) != host:
            stop_here(url, f"redirected off the host to {r.url}", "off-host",
                      url, f"third-party host: {fetch.host_of(r.url)}")
            continue
        page_kind = _kind(r.content_type)
        if page_kind is None:
            fail(url, f"content type {r.content_type or 'unknown'} is not a page — not captured", "unsupported")
            needs_operator.append(_for_operator(url, failures[-1]["reason"], "unsupported", 1))
            continue
        text_in = fetch.decode(r.body, r.content_type)
        if page_kind == "html":
            shown = visible_chars(render(text_in).text)
            scripted = "<script" in text_in.lower()
            if scripted and (shown < JS_EMPTY_CHARS or (shown < JS_SHELL_CHARS and MOUNT_RE.search(text_in))):
                copy, copy_url = try_site_copy(r.url, host, rb)
                if copy is not None and keep(url, copy, "site-copy", fetch.decode(copy.body, copy.content_type),
                                             "text", copy_of=r.url):
                    host_tally(host)["captured"].append(url)
                    continue
                stop_here(url, "js-only: the page shows almost no text without JavaScript", "js-only",
                          r.url, "js-only: not readable",
                          tried=["direct", f"site-copy {copy_url}" if copy_url else "site-copy: none"])
                continue
        if keep(url, r, "direct", text_in, page_kind):
            host_tally(host)["captured"].append(url)

    # A host that refused every page of this window, and served none, is
    # suggested closed for the surface — keyed by the first page it refused.
    for host, t in by_host.items():
        if t["refused"] and not t["captured"] and len(t["refused"]) == len(t["attempted"]) \
                and len(t["refused"]) >= HOST_REFUSAL_PAGES:
            first = t["refused"][0]
            code = next(f["reason"] for f in failures if f["url"] == first).split()[1]
            closing, _ = stops.try_line(first, f"refused: HTTP {code}", surface)
            if closing is None:
                continue  # each page is already the operator's, one by one
            needs_operator.append({
                "scope": "surface", "host": host, "pages_refused": len(t["refused"]), "next_step": "operator",
                "suggested_stop_line": closing,
                "options": OPTIONS["refused"],
                "note": f"{host} refused every page of this window and served none, and its own copy "
                        f"was tried; approving the line closes the {surface} items on {host}"})

    receipt: Dict[str, object] = {"batch": b, "kind": kind, "surface": surface, "access_date": day,
                                  "kbqa": __version__}
    state: Dict[str, object] = {"kind": kind, "batch": b, "surface": surface, "access_date": day}
    if kind == "window" and args.denominator:
        next_offset = offset + attempted
        remaining = len(selection) - next_offset
        window_end = ("error" if not blocks else
                      "exhausted" if remaining == 0 and not stopped else "budget")
        fields = {"denominator": Path(args.denominator).name, "denominator_sha256": den_sha,
                  "select": select_spec, "select_prefix": prefixes, "selected_items": len(selection),
                  "offset": offset, "window_offset": offset, "window_requested": attempted,
                  "window_returned": len(pages), "next_offset": next_offset,
                  "remaining": remaining, "window_end": window_end}
        receipt.update(fields)
        state.update(fields)
    receipt.update({"pages": pages, "failures": failures, "excluded": excluded,
                    "redirects": redirects, "stopped": stopped,
                    "stop_lines_to_add": stop_lines, "needs_operator": needs_operator,
                    "permission": permission,
                    "crawl_delay": {h: rb.crawl_delay() for h, rb in robots.items()},
                    "receipt": f"_raw/{b}/{RECEIPT}"})
    # Pages a later run can find: the URL asked for and the URL that served it.
    state.update({"pages": sorted({p["url"] for p in pages} | {p["requested"] for p in pages}),
                  "failures": failures, "kbqa": __version__})

    # The window is recorded even when nothing was captured, so the next run
    # moves on from it instead of trying the same items again for ever.
    raw_dir.mkdir(parents=True)
    _write_atomic(raw_dir / STATE, (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    def finish(code: int) -> int:
        # The subject's features as they stand before this batch's rows: what the
        # row-writer reads to tell a new feature from another source of one.
        _write_atomic(raw_dir / FEATURES, features.features_list(subject).encode("utf-8"))
        receipt["features"] = f"_raw/{b}/{FEATURES}"
        text = json.dumps(receipt, ensure_ascii=False, indent=2)
        _write_atomic(raw_dir / RECEIPT, (text + "\n").encode("utf-8"))
        print(text)
        return code

    if not blocks:
        for p in pages:
            p.pop("_parts", None)
        receipt["capture"] = None
        receipt["note"] = ("no page was captured; no capture file was written. The window is recorded, "
                           "so the next run continues after it; its pages can be retried with --retry-failed.")
        return finish(1)

    manifest = ["raw\tsha256\tbytes\tcontent_type\turl"]
    for name, body, served, sha, ctype in raws:
        _write_atomic(raw_dir / name, body)
        manifest.append(f"{name}\t{sha}\t{len(body)}\t{ctype}\t{served}")
    _write_atomic(raw_dir / "MANIFEST.tsv", ("\n".join(manifest) + "\n").encode("utf-8"))
    line = 1
    for page, block in zip(pages, blocks):  # where each page sits, so it can be read alone
        n_lines = block.count("\n")
        page["lines"] = [line, line + n_lines - 1]
        first = line + 1  # the page's first text line, after its BEGIN marker
        page["parts"] = [{"lines": [first + pt["own"][0], first + pt["own"][1]],
                          "read_from": first + pt["read_from"],
                          "breadcrumb": pt["breadcrumb"], "headings": pt["headings"]}
                         for pt in page.pop("_parts")]
        line += n_lines
    data = "".join(blocks).encode("utf-8")
    _write_atomic(capture, data)
    receipt["capture"] = str(capture)
    receipt["sha256"] = hashlib.sha256(data).hexdigest()
    return finish(0)


def main() -> None:  # pragma: no cover
    sys.exit(run())
