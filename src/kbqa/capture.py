"""kbqa capture — one window of pages, verbatim and reproducible, sized by code.

    python3 -m kbqa capture --out <subject dir> --batch <surface>-<YYYY-MM-DD>-wNN
        --denominator <file> [--select <lines>] [--offset <n>]
        [--max-pages <n>] [--max-chars <n>]
    python3 -m kbqa capture --out <d> --batch <b> --url <url>... | --urls-file <f>

**The window is sliced by code.** Given the surface's denominator, the
operator-approved selection of its lines (`--select 6,22-23,88-101`; all items
when absent) and the offset into that selection, it takes items in order until
`--max-pages` pages were attempted or the captured text passed `--max-chars`.
The agent never reads the denominator, and never decides when a window is
"too large": the receipt says `window_end` — `exhausted` only when no selected
item remains — with `next_offset` for the next window.

For each URL, in order: permission from today's robots record (`kbqa.fetch`),
the host's crawl delay, then the raw bytes. Each page's bytes are kept unedited
in `_raw/<batch>/` with their sha256 (`MANIFEST.tsv`), and the page's text —
`kbqa.htmltext`, the same rendering every time — goes into
`_capture-<batch>.raw.txt` between `=====BEGIN <url>=====` / `=====END <url>=====`
markers, keyed by the URL that served the bytes. The receipt gives each page's
line range in the capture, so the row-writer reads one page at a time.

This replaces WebFetch for captures. WebFetch hands back a model's summary of a
page and refuses to reproduce more than a short quote, so a capture written
through it could never be verbatim; this one is a fixed function of the bytes.

It never overwrites: an existing capture or raw folder stops it. It prints one
JSON receipt and exits 0 if at least one page was captured, 1 otherwise. A 429
or 503 ends the window there (`stopped: throttled`).
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

from . import __version__, fetch
from .htmltext import render, visible_chars

BATCH_RE = re.compile(r"^(product|docs|help)-\d{4}-\d{2}-\d{2}-w\d{2}$")
MARKER_RE = re.compile(r"^=====(BEGIN|END) ")
MD_LINK_URL_RE = re.compile(r"\[[^\]]+\]\((?P<url>[^)\s]+)\)")
BARE_URL_RE = re.compile(r"^\s*(?P<url>https?://\S+)\s*$")
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
    f = subject / "_stop-conditions.md"
    if not f.exists():
        return set()
    from .gates.g4_completeness import stopped_urls
    return stopped_urls(f)


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
            elif f.get("class") == "final":
                finals[f["url"]] = f
    retryable, given_up = [], []
    for url, n in runs.items():
        if url in captured or url in stopped:
            continue
        if n >= RETRY_RUNS:
            given_up.append({"url": url, "reason": last[url]["reason"], "runs": n,
                             "suggested_stop_line": f"- {url} | unreachable: {last[url]['reason']} in {n} runs"})
        else:
            retryable.append(url)
    for url, f in finals.items():
        if url not in captured and url not in stopped:
            given_up.append({"url": url, "reason": f["reason"], "runs": 1,
                             "suggested_stop_line": f"- {url} | unreachable: {f['reason']}"})
    return retryable, given_up


def _status(subject: Path, surface: str) -> int:
    windows = _windows(subject, surface)
    chain = [w for w in windows if w.get("kind") == "window"]
    retryable, given_up = _retry_state(subject, windows)
    out = {"surface": surface, "windows": [
        {k: w.get(k) for k in ("batch", "kind", "access_date", "denominator", "select", "offset",
                                "next_offset", "remaining", "window_end")} for w in windows],
           "resume_from": chain[-1]["next_offset"] if chain else 0,
           "exhausted": bool(chain) and chain[-1].get("window_end") == "exhausted",
           "retryable_failed_pages": retryable, "needs_operator": given_up}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa capture")
    ap.add_argument("--out", required=True, help="the subject folder")
    ap.add_argument("--surface", choices=("product", "docs", "help"),
                    help="name the next free batch of this surface for today")
    ap.add_argument("--batch", help="an explicit batch name (tests; the fetcher uses --surface)")
    ap.add_argument("--denominator", help="the surface's denominator; the window is sliced from it")
    ap.add_argument("--select", help="the approved denominator lines, e.g. 6,22-23,88-101")
    ap.add_argument("--offset", type=int, default=None, help="where in the selection this window begins")
    ap.add_argument("--resume", action="store_true", help="begin where the surface's recorded windows stopped")
    ap.add_argument("--retry-failed", action="store_true", help="retry pages that failed in earlier windows")
    ap.add_argument("--status", action="store_true", help="report the surface's recorded windows; fetch nothing")
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
        print(json.dumps({"batch": b or None, "refused": msg, **extra}, ensure_ascii=False, indent=2))
        return 1

    if not subject.is_dir():
        return refuse(f"no subject folder {subject}")
    surface = args.surface or (b.split("-", 1)[0] if b else None)
    if surface not in ("product", "docs", "help"):
        return refuse("give --surface (or a batch name that starts with one)")
    if args.status:
        return _status(subject, surface)
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

    kind = "window"
    selection: List[str] = []
    den_sha = None
    select_spec = args.select or "all"
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
        den_sha = _sha(den)
        if args.resume:
            chain = [w for w in _windows(subject, surface) if w.get("kind") == "window"]
            if not chain:
                return refuse("nothing to resume: no window of this surface is recorded")
            for w in chain:
                if w["denominator"] != den.name or w["denominator_sha256"] != den_sha:
                    return refuse(f"window {w['batch']} was cut from another denominator "
                                  f"({w['denominator']}) — resuming would point at other items")
                if w["select"] != (args.select or chain[0]["select"]):
                    return refuse(f"window {w['batch']} used the selection {w['select']!r}, "
                                  f"not {args.select!r} — scope would drift")
            if chain[0]["offset"] != 0:
                return refuse(f"the first recorded window {chain[0]['batch']} does not start at 0")
            for prev, nxt in zip(chain, chain[1:]):
                if nxt["offset"] != prev["next_offset"]:
                    return refuse(f"windows {prev['batch']} and {nxt['batch']} leave a gap or overlap "
                                  f"({prev['next_offset']} → {nxt['offset']})")
            if chain[-1]["window_end"] == "exhausted":
                return refuse("the selection is exhausted: every selected item was attempted")
            select_spec = chain[0]["select"]
            offset = chain[-1]["next_offset"]
        by_line = dict(denominator_items(den))
        if select_spec != "all":
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
    pacer = fetch.Pacer()
    pages, failures, excluded, redirects, stop_lines = [], [], [], [], []
    blocks: List[str] = []
    raws: List[tuple] = []
    stopped = None
    attempted = 0
    chars = 0

    def fail(url: str, reason: str, cls: str, attempts: int = 1) -> None:
        failures.append({"url": url, "reason": reason, "class": cls, "attempts": attempts})
        if cls == "final":
            needs_operator.append({"url": url, "reason": reason, "runs": 1,
                                   "suggested_stop_line": f"- {url} | unreachable: {reason}"})

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
            rb = robots.get(host) or robots.setdefault(host, fetch.robots_for(subject, host, day))
        except fetch.FetchError as exc:
            return refuse(str(exc))
        if rb.site_wide_refused():
            fail(url, "refused: robots (site-wide)", "refused")
            stop_lines.append(f"- {url} | refused: robots")
            continue
        ok, rule = rb.check(url)
        if not ok:
            excluded.append({"url": url, "rule": rule})
            stop_lines.append(f"- {url} | excluded: robots {rule}")
            continue
        pacer.wait(host, rb.crawl_delay())
        r, cls, tries, reason = fetch.get_patiently(url)
        if cls == "throttled":
            fail(url, f"{reason} — throttled; window ended here", "throttled", tries)
            attempted -= 1  # not taken: the next window starts again at this item
            stopped = {"reason": "throttled", "not_attempted": candidates[i:]}
            break
        if cls != "ok":
            fail(url, reason, cls, tries)
            continue
        if fetch.host_of(r.url) != host:
            fail(url, f"redirected off the host to {r.url}", "off-host")
            stop_lines.append(f"- {url} | third-party host: {fetch.host_of(r.url)}")
            continue
        page_kind = _kind(r.content_type)
        if page_kind is None:
            fail(url, f"content type {r.content_type or 'unknown'} is not a page — not captured", "unsupported")
            continue
        text_in = fetch.decode(r.body, r.content_type)
        if page_kind == "html":
            rendered = render(text_in)
            text, heads, crumb = rendered.text, rendered.headings, rendered.breadcrumb
        else:
            text = text_in.replace("\r\n", "\n").rstrip("\n")
            heads = [(j, len(m.group(1)), m.group(2)) for j, ln in enumerate(text.split("\n"))
                     if (m := MD_HEADING_RE.match(ln))]
            crumb = None
        shown = visible_chars(text)
        scripted = "<script" in text_in.lower()
        if page_kind == "html" and scripted and (shown < JS_EMPTY_CHARS
                                                 or (shown < JS_SHELL_CHARS and MOUNT_RE.search(text_in))):
            fail(url, "js-only: the page shows almost no text without JavaScript", "js-only")
            stop_lines.append(f"- {r.url} | js-only: not readable")
            continue
        if any(MARKER_RE.match(ln) for ln in text.splitlines()):
            fail(url, "the page's text contains a capture marker line", "unsupported")
            continue
        if r.url != url:
            redirects.append({"requested": url, "served": r.url})
        n = len(raws) + 1
        ext = "html" if page_kind == "html" else "txt"
        raw_name = f"{n:03d}.{ext}"
        raw_sha = hashlib.sha256(r.body).hexdigest()
        raws.append((raw_name, r.body, r.url, raw_sha, r.content_type))
        blocks.append(f"=====BEGIN {r.url}=====\n{text}\n=====END {r.url}=====\n")
        chars += len(text)
        pages.append({"url": r.url, "requested": url, "fetch_method": "direct", "status": r.status,
                      "content_type": r.content_type, "bytes": len(r.body),
                      "raw": f"_raw/{b}/{raw_name}", "raw_sha256": raw_sha,
                      "text_chars": shown, "oversize": len(text) > args.max_chars,
                      "_parts": parts_of(text.split("\n"), heads, crumb, args.part_chars)})

    receipt: Dict[str, object] = {"batch": b, "kind": kind, "surface": surface, "access_date": day}
    state: Dict[str, object] = {"kind": kind, "batch": b, "surface": surface, "access_date": day}
    if kind == "window" and args.denominator:
        next_offset = offset + attempted
        remaining = len(selection) - next_offset
        window_end = ("error" if not blocks else
                      "exhausted" if remaining == 0 and not stopped else "budget")
        fields = {"denominator": Path(args.denominator).name, "denominator_sha256": den_sha,
                  "select": select_spec, "selected_items": len(selection),
                  "offset": offset, "window_offset": offset, "window_requested": attempted,
                  "window_returned": len(pages), "next_offset": next_offset,
                  "remaining": remaining, "window_end": window_end}
        receipt.update(fields)
        state.update(fields)
    receipt.update({"pages": pages, "failures": failures, "excluded": excluded,
                    "redirects": redirects, "stopped": stopped,
                    "stop_lines_to_add": stop_lines, "needs_operator": needs_operator,
                    "crawl_delay": {h: rb.crawl_delay() for h, rb in robots.items()}})
    # Pages a later run can find: the URL asked for and the URL that served it.
    state.update({"pages": sorted({p["url"] for p in pages} | {p["requested"] for p in pages}),
                  "failures": failures, "kbqa": __version__})

    # The window is recorded even when nothing was captured, so the next run
    # moves on from it instead of trying the same items again for ever.
    raw_dir.mkdir(parents=True)
    _write_atomic(raw_dir / STATE, (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    if not blocks:
        receipt["capture"] = None
        receipt["note"] = ("no page was captured; no capture file was written. The window is recorded, "
                           "so the next run continues after it; its pages can be retried with --retry-failed.")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 1

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
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(run())
