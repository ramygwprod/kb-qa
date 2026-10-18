"""kbqa stop — the one stop-condition vocabulary, and the one way to add a line.

    python3 -m kbqa stop add <subject dir> "- <url> | <reason>"
    python3 -m kbqa stop reasons

A stop-condition says why an index item has no row: `- <url> | <reason>`, one
line per stop, in `_stop-conditions.md`. Its reasons are defined here and
nowhere else. Every stop line `kbqa capture` and `kbqa index` suggest is built
from this list, `kbqa stop add` accepts only lines that read as one of these
reasons, and the fetcher's reason table is tested against it — so a suggested
line can never be one the fetcher's table does not know (in v6.17.1 capture
suggested `unreachable:` lines that the table did not list).

`add` appends one line atomically: an exclusive lock on the file, one write
in append mode, flushed and synced before the lock is released, so two
fetchers adding lines at once never lose one. A line already present is not
added twice. Lines are only ever added — never changed, never removed.
"""

import argparse
import fcntl
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

STOPS_NAME = "_stop-conditions.md"
SURFACES = ("product", "docs", "help")


@dataclass(frozen=True)
class Reason:
    wording: str     # as the fetcher's table shows it
    pattern: str     # the reason, matched whole
    when: str        # the fetcher's table: when the reason applies
    closes_surface: bool = False  # may end with ` (surface <slug>)`


REASONS: Tuple[Reason, ...] = (
    Reason("surface <slug> not published: <what that page shows>",
           r"surface (?:product|docs|help) not published: \S.*",
           "a surface does not exist"),
    Reason("refused: robots", r"refused: robots",
           "G0 exit 2, or a host refused site-wide", True),
    Reason("refused: HTTP <401 or 403>", r"refused: HTTP (?:401|403)",
           "the host refuses our fetcher although robots allows it, and the site's own copy was "
           "tried — only with the operator's word", True),
    Reason("excluded: robots <path>", r"excluded: robots \S+",
           "robots closes the path to us", True),
    Reason("js-only: not readable", r"js-only: not readable",
           "the page shows no text without JavaScript, and the site's own copy was tried", True),
    Reason("gated: login", r"gated: login", "the page needs a login", True),
    Reason("third-party host: <host>", r"third-party host: [a-z0-9.-]+",
           "the link or a redirect leads off the subject's own hosts", True),
    Reason("not approved: pdf", r"not approved: pdf", "a PDF the operator has not approved"),
    Reason("unreachable: <the failure kbqa printed>", r"unreachable: \S.*",
           "a page no attempt could fetch (a 404, a TLS failure, a page failing in three runs) — "
           "only with the operator's word", True),
    Reason("no feature: <what the page is>", r"no feature: \S.*",
           "a page you captured from which the row-writer recorded no row — say what the page is "
           "(`pricing page`, `legal notice`, `blog index`)"),
)

SURFACE_SUFFIX_RE = re.compile(r"^(?P<reason>.*\S) \(surface (?P<surface>product|docs|help)\)$")
LINE_RE = re.compile(r"^- (?P<url>https?://\S+) \| (?P<reason>\S.*)$")


class StopLineError(ValueError):
    """A line that is not `- <url> | <reason>` with a reason from REASONS."""


def classify(reason: str) -> Tuple[Reason, Optional[str]]:
    """(the vocabulary entry, the surface the reason closes or None)."""
    m = SURFACE_SUFFIX_RE.match(reason)
    if m:  # the suffix first: `unreachable: …` would otherwise swallow it
        for r in REASONS:
            if r.closes_surface and re.fullmatch(r.pattern, m.group("reason")):
                return r, m.group("surface")
        # A free-text reason (`no feature: …`) must not end like a closing line:
        # the surfaces check would read it as closing the surface.
        raise StopLineError(
            f"reason {reason!r} ends with `(surface {m.group('surface')})`, but only these reasons may close "
            "a surface: " + "; ".join(r.wording for r in REASONS if r.closes_surface))
    for r in REASONS:
        if re.fullmatch(r.pattern, reason):
            return r, None
    raise StopLineError(
        f"reason {reason!r} is not in the vocabulary. A reason is one of: "
        + "; ".join(r.wording for r in REASONS)
        + " — the closing ones may end with ` (surface <slug>)`")


def parse_line(text: str) -> Tuple[str, str, Reason, Optional[str]]:
    """(url, reason, its vocabulary entry, the surface it closes) for one stop line."""
    m = LINE_RE.match(text.strip())
    if not m:
        raise StopLineError(f"{text!r} is not a stop line: `- <url> | <reason>`, keyed by a fetched URL")
    reason, surface = classify(m.group("reason"))
    return m.group("url"), m.group("reason"), reason, surface


def line(url: str, reason: str, surface: Optional[str] = None) -> str:
    """A stop line, built from the vocabulary — the only way kbqa writes one."""
    text = f"- {url} | {reason}" + (f" (surface {surface})" if surface else "")
    parse_line(text)  # never suggest a line the vocabulary does not know
    return text


def add(subject: Path, text: str) -> dict:
    """Append one stop line to the subject's file, atomically, once."""
    url, reason, _, surface = parse_line(text)
    text = text.strip()
    path = subject / STOPS_NAME
    with open(path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            existing = fh.read()
            present = [ln.strip() for ln in existing.splitlines()]
            if text in present:
                return {"added": False, "line": text, "note": "already recorded; not added twice"}
            same_url = [ln for ln in present if LINE_RE.match(ln) and LINE_RE.match(ln).group("url") == url]
            data = ("" if not existing or existing.endswith("\n") else "\n") + text + "\n"
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    out = {"added": True, "line": text, "file": str(path)}
    if surface:
        out["closes_surface"] = surface
    if same_url:
        out["same_url_lines"] = same_url
    return out


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa stop")
    sub = ap.add_subparsers(dest="action", required=True)
    a = sub.add_parser("add", help="append one stop line, checked against the vocabulary")
    a.add_argument("subject", help="the subject folder")
    a.add_argument("line", help='"- <url> | <reason>"')
    sub.add_parser("reasons", help="print the vocabulary")
    args = ap.parse_args(argv)

    if args.action == "reasons":
        print(json.dumps([{"reason": r.wording, "when": r.when, "closes_surface": r.closes_surface}
                          for r in REASONS], ensure_ascii=False, indent=2))
        return 0
    subject = Path(args.subject)
    if not subject.is_dir():
        print(json.dumps({"refused": f"no subject folder {subject}", "next_step": "operator"}, indent=2))
        return 1
    try:
        out = add(subject, args.line)
    except StopLineError as exc:
        print(json.dumps({"refused": str(exc), "next_step": "operator"}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(run())
