"""kbqa collect-surface — one surface's capture windows, run until code says stop.

    python3 -m kbqa collect-surface --out <subject dir> --surface <s> --denominator <file>
        [--select <lines> | --select-prefix <path>...] [--max-windows <n>]
        [--max-pages <n>] [--max-chars <n>]

The loop the fetcher used to run by hand, as code. It calls `kbqa capture`'s
own `run`, in this process: the first window of the surface (or `--resume`
when windows cut from this denominator are already recorded), then `--resume`
again, until

- the selection is `exhausted` (the receipt's `window_end`);
- a window ends `throttled` (a 429 or 503; the next run resumes at that page);
- a window captured nothing (`window_end: error`): the surface stops for the
  operator, as it always has; the window is recorded, so a later run goes on
  after it;
- capture refuses (`refused` — returned word for word), or a host's robots.txt
  stays unreachable (`robots_unreachable`);
- `--max-windows` windows (10 by default) were written in this run.

When the surface is exhausted and failed pages may still pass, it runs
`--retry-failed` once; capture's own limit (a page is retried in at most three
runs) stays the limit.

It lists, under `unstaged`, every window of this surface — this run's and every
earlier run's — that has a capture file and no staging file, in batch order,
each with its state: no drafts yet, drafts not yet staged, or every page drafted
`no_row` (nothing to stage). The collect skill runs the per-window steps for
those before anything new, so a window captured in a run that stopped half-way
is never lost.

It writes nothing itself: every file is capture's. It never stages rows or
maps: the row-writer and the mappers still run per window, after it, in the
order the collect skill gives, so the lists `kbqa stage --lists` builds hold
every row written so far.

It prints one JSON: every window written (batch, `window_end`, pages captured,
copies, failures, receipt and capture paths), the `unstaged` windows, the end
state, one merged
`needs_operator` list (each URL once; a host's surface-wide item once per
host), the merged `stop_lines_to_add` (each line once) and the next step. It
exits 0 when a window captured a page or the surface was already exhausted, 1
otherwise.
"""

import argparse
import contextlib
import io
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import capture

MAX_WINDOWS = 10

NEXT_STEP = {
    "exhausted": "the selection is exhausted: nothing is left to capture for this surface. Bring every "
                 "needs_operator item to the operator",
    "throttled": "the host is throttling us: run collect-surface again later; it resumes at the page that "
                 "was throttled. Never switch fetcher, user-agent or route",
    "refused": "capture refused: bring the refusal to the operator word for word; never run again "
               "until they rule",
    "robots_unreachable": "a host's robots.txt could not be read: nothing more is fetched from it. The "
                          "operator decides: hold the host, or run collect-surface again later",
    "error": "the last window captured nothing: stop this surface and bring that window's failures to "
             "the operator. The window is recorded, so running again goes on after it",
    "window_limit": "the run's window budget is used: run collect-surface again to continue",
}


def _capture(argv: List[str]) -> Tuple[int, Dict]:
    """capture's own run, in this process; its one printed JSON, read back."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = capture.run(argv)
    return code, json.loads(out.getvalue())


def end_of(r: Dict) -> Optional[str]:
    """The end state one capture result calls for, or None to go on."""
    if "refused" in r:
        return "robots_unreachable" if r.get("robots_unreachable") else "refused"
    if (r.get("stopped") or {}).get("reason") == "throttled":
        return "throttled"
    if r.get("window_end") == "exhausted":
        return "exhausted"
    if r.get("window_end") == "error":
        return "error"
    return None


def _key(item: Dict) -> object:
    if item.get("url"):
        return item["url"]
    return ("host", item.get("host"))  # a surface-wide item: one per host


def merge_operator(into: List[Dict], items: List[Dict]) -> None:
    """Add each item whose URL (or, for a surface-wide item, host) is not in yet."""
    seen = {_key(x) for x in into}
    for item in items:
        k = _key(item)
        if k not in seen:
            seen.add(k)
            into.append(item)


def merge_lines(into: List[str], lines: List[str]) -> None:
    for ln in lines:
        if ln not in into:
            into.append(ln)


def _window(r: Dict) -> Dict[str, object]:
    return {"batch": r.get("batch"), "kind": r.get("kind"), "window_end": r.get("window_end"),
            "stopped": (r.get("stopped") or {}).get("reason"),
            "pages_captured": len(r.get("pages") or []), "duplicates": len(r.get("duplicates") or []),
            "failures": len(r.get("failures") or []), "next_offset": r.get("next_offset"),
            "remaining": r.get("remaining"), "receipt": r.get("receipt"), "capture": r.get("capture")}


def _chain(subject: Path, surface: str, den: Path) -> List[Dict]:
    """The windows recorded for this surface from this denominator."""
    if not subject.is_dir():
        return []
    return capture._chain(capture._windows(subject, surface), den.name)


NO_DRAFTS = "no drafts: the per-window steps, from kbqa stage --lists"
DRAFTED = "drafts written, no staging file: kbqa stage, then the per-window steps after it"
ALL_NO_ROW = "every page drafted no_row: no rows, nothing to stage or map"


def _all_no_row(draft: Path, receipt: Path) -> bool:
    """The drafts are `no_row` lines only, one for every page of the receipt."""
    try:
        pages = {p.get("url") for p in json.loads(receipt.read_text(encoding="utf-8")).get("pages") or []}
        objs = [json.loads(ln) for ln in draft.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, ValueError, AttributeError):
        return False
    return bool(objs) and all(isinstance(o, dict) and set(o) == {"page", "no_row"} for o in objs) \
        and {o["page"] for o in objs} == pages


def unstaged(subject: Path, surface: str) -> List[Dict[str, object]]:
    """Every window of this surface — this run's and every earlier run's, from
    any denominator — that has a capture file and no staging file, in batch
    order: rows not yet written are never lost between runs."""
    out: List[Dict[str, object]] = []
    if not subject.is_dir():
        return out
    for w in capture._windows(subject, surface):
        b = str(w.get("batch"))
        cap = subject / f"_capture-{b}.raw.txt"
        if not cap.is_file() or (subject / f"_collect-{b}-staging.md").exists():
            continue
        draft, receipt = subject / f"_draft-{b}.jsonl", subject / "_raw" / b / capture.RECEIPT
        state = (NO_DRAFTS if not draft.is_file() else
                 ALL_NO_ROW if _all_no_row(draft, receipt) else DRAFTED)
        out.append({"batch": b, "capture": str(cap), "receipt": f"_raw/{b}/{capture.RECEIPT}", "state": state})
    return out


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa collect-surface")
    ap.add_argument("--out", required=True, help="the subject folder")
    ap.add_argument("--surface", required=True, choices=("product", "docs", "help"))
    ap.add_argument("--denominator", required=True, help="the surface's current denominator")
    ap.add_argument("--select", help="the approved denominator lines, e.g. 6,22-23,88-101")
    ap.add_argument("--select-prefix", action="append", default=[],
                    help="the approved items whose URL path starts with this (repeatable)")
    ap.add_argument("--max-windows", type=int, default=MAX_WINDOWS,
                    help="at most this many windows are written in this run")
    ap.add_argument("--max-pages", type=int, default=capture.MAX_PAGES)
    ap.add_argument("--max-chars", type=int, default=capture.MAX_CHARS)
    ap.add_argument("--date", default=None, help="access date (tests)")
    args = ap.parse_args(argv)

    subject, den, surface = Path(args.out), Path(args.denominator), args.surface
    if args.max_windows < 1:
        print(json.dumps({"surface": surface, "refused": "--max-windows must be at least 1",
                          "next_step": "operator"}, ensure_ascii=False, indent=2))
        return 1
    base = ["--out", str(subject), "--surface", surface] + (["--date", args.date] if args.date else [])
    scope = (["--select", args.select] if args.select else []) + \
        [a for p in args.select_prefix for a in ("--select-prefix", p)]
    window_args = base + ["--denominator", str(den)] + scope + \
        ["--max-pages", str(args.max_pages), "--max-chars", str(args.max_chars)]

    windows: List[Dict] = []
    needs_operator: List[Dict] = []
    stop_lines: List[str] = []
    permission: List[Dict] = []
    refusal: Optional[Dict] = None
    end: Optional[str] = None

    def take(r: Dict) -> Optional[str]:
        nonlocal refusal
        merge_operator(needs_operator, r.get("needs_operator") or [])
        merge_lines(stop_lines, r.get("stop_lines_to_add") or [])
        permission.extend(r.get("permission") or [])
        if "refused" in r:
            refusal = r
        else:
            windows.append(_window(r))
        return end_of(r)

    # A surface whose recorded windows already reached the end of the selection
    # is not asked again (capture would refuse it); only its failed pages are.
    chain = _chain(subject, surface, den)
    current = capture.current_denominator(den.parent, surface) if den.parent.is_dir() else None
    already_exhausted = bool(chain) and chain[-1].get("window_end") == "exhausted" \
        and current is not None and current.name == den.name
    if already_exhausted:
        end = "exhausted"
    while end is None:
        if len(windows) >= args.max_windows:
            end = "window_limit"
            break
        resume = ["--resume"] if _chain(subject, surface, den) else []
        end = take(_capture(window_args + resume)[1])

    retried = False
    if end == "exhausted":  # failed pages wait for the end of the selection
        retryable, _ = capture._retry_state(subject, capture._windows(subject, surface))
        if retryable:
            retried = True
            end = take(_capture(base + ["--retry-failed"])[1]) or "exhausted"
    if end == "exhausted" and subject.is_dir():
        # Pages given up on after their last run are the operator's, whichever
        # run gave them up.
        _, given_up = capture._retry_state(subject, capture._windows(subject, surface))
        merge_operator(needs_operator, given_up)

    out: Dict[str, object] = {
        "surface": surface, "denominator": den.name, "end": end, "next_step": NEXT_STEP[end],
        "already_exhausted": already_exhausted, "retried_failed": retried,
        "windows": windows, "unstaged": unstaged(subject, surface), "needs_operator": needs_operator,
        "stop_lines_to_add": stop_lines, "permission": permission}
    if refusal is not None:
        out["refusal"] = refusal
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if already_exhausted or any(w["pages_captured"] for w in windows) else 1


def main() -> None:  # pragma: no cover
    import sys
    sys.exit(run())
