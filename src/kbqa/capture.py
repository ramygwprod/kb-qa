"""kbqa capture — one window of pages, verbatim and reproducible.

    python3 -m kbqa capture --out <subject dir> --batch <surface>-<YYYY-MM-DD>-wNN
                            --url <url> [--url <url> ...] | --urls-file <file>

For each URL, in order: permission from today's robots record (`kbqa.fetch`),
the host's crawl delay, then the raw bytes. Each page's bytes are kept unedited
in `_raw/<batch>/` with their sha256 (`MANIFEST.tsv`), and the page's text —
`kbqa.htmltext`, the same rendering every time — goes into
`_capture-<batch>.raw.txt` between `=====BEGIN <url>=====` / `=====END <url>=====`
markers, keyed by the URL that served the bytes.

This replaces WebFetch for captures. WebFetch hands back a model's summary of a
page and refuses to reproduce more than a short quote, so a capture written
through it could never be verbatim; this one is a fixed function of the bytes.

It never overwrites: an existing capture or raw folder stops it. It prints one
JSON receipt — what the fetcher returns — and exits 0 if at least one page was
captured, 1 otherwise. A 429 or 503 ends the window there (`stopped: throttled`).
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from . import fetch
from .htmltext import html_to_text, visible_chars

BATCH_RE = re.compile(r"^(product|docs|help)-\d{4}-\d{2}-\d{2}-w\d{2}$")
MARKER_RE = re.compile(r"^=====(BEGIN|END) ")
# A JavaScript shell: almost no text, or little text around an app mount point.
# A short page that is simply short is not a shell.
JS_EMPTY_CHARS = 50
JS_SHELL_CHARS = 200
MOUNT_RE = re.compile(r"""<div[^>]+id=["'](root|app|__next|__nuxt|svelte)["']""", re.I)
TEXT_TYPES = ("text/plain", "text/markdown", "text/x-markdown")


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


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa capture")
    ap.add_argument("--out", required=True, help="the subject folder")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--urls-file")
    ap.add_argument("--date", default=None, help="access date (tests)")
    args = ap.parse_args(argv)

    subject = Path(args.out)
    day = args.date or date.today().isoformat()
    b = args.batch
    urls: List[str] = list(args.url)
    if args.urls_file:
        urls += [ln.strip() for ln in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
    urls = list(dict.fromkeys(urls))  # in order, once each

    def refuse(msg: str) -> int:
        print(json.dumps({"batch": b, "refused": msg}, ensure_ascii=False, indent=2))
        return 1

    if not subject.is_dir():
        return refuse(f"no subject folder {subject}")
    if not BATCH_RE.match(b):
        return refuse(f"batch {b!r} is not <surface>-<YYYY-MM-DD>-wNN")
    if b.split("-", 1)[1][:10] != day:
        return refuse(f"batch {b!r} is not dated with today's access date {day}")
    if not urls:
        return refuse("no URLs given")
    capture = subject / f"_capture-{b}.raw.txt"
    raw_dir = subject / "_raw" / b
    if capture.exists() or raw_dir.exists():
        return refuse(f"{capture.name} or _raw/{b}/ already exists — a batch name is never reused")

    robots: Dict[str, fetch.Robots] = {}
    pacer = fetch.Pacer()
    pages, failures, excluded, redirects, stop_lines = [], [], [], [], []
    blocks: List[str] = []
    raws: List[tuple] = []
    stopped = None

    for i, url in enumerate(urls):
        host = fetch.host_of(url)
        try:
            rb = robots.get(host) or robots.setdefault(host, fetch.robots_for(subject, host, day))
        except fetch.FetchError as exc:
            return refuse(str(exc))
        if rb.site_wide_refused():
            failures.append({"url": url, "reason": "refused: robots (site-wide)"})
            stop_lines.append(f"- {url} | refused: robots")
            continue
        ok, rule = rb.check(url)
        if not ok:
            excluded.append({"url": url, "rule": rule})
            stop_lines.append(f"- {url} | excluded: robots {rule}")
            continue
        pacer.wait(host, rb.crawl_delay())
        try:
            r = fetch.get(url)
        except fetch.FetchError as exc:
            failures.append({"url": url, "reason": str(exc)})
            continue
        if r.status in fetch.THROTTLE_STATUSES:
            failures.append({"url": url, "reason": f"HTTP {r.status} — throttled; window ended here"})
            stopped = {"reason": "throttled", "not_attempted": urls[i + 1:]}
            break
        if r.status != 200:
            failures.append({"url": url, "reason": f"HTTP {r.status}"})
            continue
        if fetch.host_of(r.url) != host:
            failures.append({"url": url, "reason": f"redirected off the host to {r.url}"})
            stop_lines.append(f"- {url} | third-party host: {fetch.host_of(r.url)}")
            continue
        kind = _kind(r.content_type)
        if kind is None:
            failures.append({"url": url, "reason": f"content type {r.content_type or 'unknown'} is not a page — not captured"})
            continue
        text_in = fetch.decode(r.body, r.content_type)
        text = html_to_text(text_in) if kind == "html" else text_in.replace("\r\n", "\n").rstrip("\n")
        shown = visible_chars(text)
        if kind == "html" and (shown < JS_EMPTY_CHARS
                               or (shown < JS_SHELL_CHARS and MOUNT_RE.search(text_in))):
            failures.append({"url": url, "reason": "js-only: the page shows almost no text without JavaScript"})
            stop_lines.append(f"- {r.url} | js-only: not readable")
            continue
        if any(MARKER_RE.match(ln) for ln in text.splitlines()):
            failures.append({"url": url, "reason": "the page's text contains a capture marker line"})
            continue
        if r.url != url:
            redirects.append({"requested": url, "served": r.url})
        n = len(raws) + 1
        ext = "html" if kind == "html" else "txt"
        raw_name = f"{n:03d}.{ext}"
        raw_sha = hashlib.sha256(r.body).hexdigest()
        raws.append((raw_name, r.body, r.url, raw_sha, r.content_type))
        blocks.append(f"=====BEGIN {r.url}=====\n{text}\n=====END {r.url}=====\n")
        pages.append({"url": r.url, "fetch_method": "direct", "status": r.status,
                      "content_type": r.content_type, "bytes": len(r.body),
                      "raw": f"_raw/{b}/{raw_name}", "raw_sha256": raw_sha,
                      "text_chars": visible_chars(text)})

    receipt = {"batch": b, "access_date": day, "pages": pages, "failures": failures,
               "excluded": excluded, "redirects": redirects, "stopped": stopped,
               "stop_lines_to_add": stop_lines,
               "crawl_delay": {h: rb.crawl_delay() for h, rb in robots.items()}}
    if not blocks:
        receipt["capture"] = None
        receipt["note"] = "no page was captured; no capture file was written"
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 1

    raw_dir.mkdir(parents=True)
    manifest = ["raw\tsha256\tbytes\tcontent_type\turl"]
    for name, body, served, sha, ctype in raws:
        _write_atomic(raw_dir / name, body)
        manifest.append(f"{name}\t{sha}\t{len(body)}\t{ctype}\t{served}")
    _write_atomic(raw_dir / "MANIFEST.tsv", ("\n".join(manifest) + "\n").encode("utf-8"))
    data = "".join(blocks).encode("utf-8")
    _write_atomic(capture, data)
    receipt["capture"] = str(capture)
    receipt["sha256"] = hashlib.sha256(data).hexdigest()
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(run())
