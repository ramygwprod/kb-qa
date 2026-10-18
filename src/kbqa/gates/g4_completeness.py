"""G4 · Completeness — g4 --denominator <f> --rows <f>... [--stops <f>]

Report EXISTENCE and EVIDENCE as two numbers, never blended. Knowing a thing
exists and having sourced it are different states, and averaging them hides
exactly the gap this gate is for.

No target number. Three named things is DONE at three. (spec §G4)
"""

import argparse
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

from ..parsing import normalise_for_match, parse_staging
from ..verdict import FAIL, PASS, Finding, Verdict, input_ref
from . import EXIT_FAIL, EXIT_PASS

GATE = "g4_completeness"

MD_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)\s]+)\)")
BARE_URL_RE = re.compile(r"^\s*(?P<url>https?://\S+)\s*$")
STOP_RE = re.compile(r"^(?P<key>.+?)\s*:\s+(?P<reason>.+?)\s*$")


def _label_key(label: str) -> str:
    return normalise_for_match(label).casefold()


def parse_denominator(path: Path) -> List[Tuple[str, str]]:
    """Extract (label, url) index items. Markdown links first, bare URLs after."""
    items: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        matched = False
        for m in MD_LINK_RE.finditer(line):
            url = m.group("url").strip()
            if url in seen:
                continue
            seen.add(url)
            items.append((m.group("label").strip(), url))
            matched = True
        if matched:
            continue
        bare = BARE_URL_RE.match(line)
        if bare:
            url = bare.group("url").strip()
            if url in seen:
                continue
            seen.add(url)
            # No label given; the last path segment is the vendor's own name for it.
            segs = [s for s in urlsplit(url).path.split("/") if s]
            items.append((segs[-1] if segs else url, url))
    return items


def disambiguate(items: List[Tuple[str, str]]) -> Dict[str, Tuple[str, str]]:
    """Give every index item a unique key.

    Colliding labels are disambiguated by walking UP the vendor's own URL path
    until unique — 16 pages named `syntax-reference` must not collapse to one.
    """
    by_label: Dict[str, List[Tuple[str, str]]] = {}
    for label, url in items:
        by_label.setdefault(_label_key(label), []).append((label, url))

    resolved: Dict[str, Tuple[str, str]] = {}
    for key, group in by_label.items():
        if len(group) == 1:
            resolved[key] = group[0]
            continue
        depth = 1
        pending = list(group)
        while pending:
            trial: Dict[str, List[Tuple[str, str]]] = {}
            for label, url in pending:
                segs = [s for s in urlsplit(url).path.split("/") if s]
                tail = "/".join(segs[-(depth + 1):]) if segs else url
                trial.setdefault(f"{key}@{tail}".casefold(), []).append((label, url))
            still: List[Tuple[str, str]] = []
            for tkey, tgroup in trial.items():
                if len(tgroup) == 1:
                    resolved[tkey] = tgroup[0]
                else:
                    still.extend(tgroup)
            if len(still) == len(pending):
                # Walking up gained nothing; fall back to the full URL, which is
                # unique by construction. Never silently merge distinct pages.
                for label, url in still:
                    resolved[f"{key}@{url}"] = (label, url)
                break
            pending = still
            depth += 1
    return resolved


STOP_PIPE_RE = re.compile(r"^(?P<key>\S.*?)\s+\|\s+(?P<reason>.*?)\s*$")
LIST_ITEM_RE = re.compile(r"^\s*[-*]\s+")
FENCE_RE = re.compile(r"^\s*```")


def read_stop_entries(path: Path) -> Tuple[List[Tuple[str, str, int]], List[str], int]:
    """Stop-condition entries as (key, reason, line_no), errors, lines ignored.

    The file's documented form is `<url> | <reason>`, one per line, and the
    estate's files carry YAML frontmatter and prose around those lines. The
    earlier parser read every non-blank line as an entry in `<key>: <reason>`
    form, so on a real file it reported the frontmatter keys as stop-conditions
    and every `<url> | <reason>` line without a later `: ` as "no reason" —
    11 false findings on one subject.

    An ENTRY is a line inside a ``` fence, a list item, or a line that starts
    with a URL. Everything else — frontmatter, headings, prose — is commentary,
    and is counted rather than silently dropped. Both separators are accepted;
    an entry with neither is still an error.
    """
    entries: List[Tuple[str, str, int]] = []
    errors: List[str] = []
    ignored = 0
    lines = path.read_text(encoding="utf-8").splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
        ignored += start
    in_fence = False
    for line_no, line in enumerate(lines[start:], start=start + 1):
        s = line.strip()
        if FENCE_RE.match(s):
            in_fence = not in_fence
            continue
        if not s:
            continue
        is_item = bool(LIST_ITEM_RE.match(line))
        if not (in_fence or is_item or s.startswith(("http://", "https://"))):
            ignored += 1
            continue
        s = LIST_ITEM_RE.sub("", s).strip()
        m = STOP_PIPE_RE.match(s) or STOP_RE.match(s)
        if not m or not m.group("reason").strip():
            errors.append(
                f"line {line_no}: stop-condition has no reason: {line.strip()!r} "
                "(expected '<url> | <reason>' or '<url-or-label>: <reason>')"
            )
            continue
        entries.append((m.group("key").strip(), m.group("reason").strip(), line_no))
    return entries, errors, ignored


def parse_stops(path: Path) -> Tuple[Dict[str, str], List[str]]:
    """Stop-conditions keyed by URL or label. Each MUST carry a reason."""
    entries, errors, _ = read_stop_entries(path)
    return {k: r for k, r, _ in entries}, errors


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def closing_hosts(denom: Path, stops: Dict[str, str]) -> Dict[str, str]:
    """{host: the URL keying its line} for each stop line that closes this
    denominator's surface: a reason from the vocabulary (`kbqa.stops`) ending
    `(surface <slug>)`, where the slug is the surface named in the
    denominator's file name. Such a line closes the surface's remaining items
    on the host of its own URL, and nowhere else — a help host refusing our
    fetcher closes the help items on that host, never another host's."""
    from .. import stops as vocabulary
    m = re.match(r"^_denominator-(?P<surface>product|docs|help)-", denom.name)
    if not m:
        return {}
    out: Dict[str, str] = {}
    for key, reason in stops.items():
        if not key.startswith(("http://", "https://")):
            continue
        try:
            _, surface = vocabulary.classify(reason)
        except vocabulary.StopLineError:
            continue
        if surface == m.group("surface"):
            out.setdefault(_host(key), key)
    return out


def _int_or_none(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return None


def stopped_urls(path: Optional[Path]) -> Set[str]:
    """The URLs that key a stop-condition with a reason, from a stops file."""
    if path is None or not path.exists():
        return set()
    stops, _ = parse_stops(path)
    return {k for k in stops if k.startswith(("http://", "https://"))}


def read_windows(
    rows_files: List[str], findings: List[Finding], stops: Optional[Set[str]] = None
) -> List[Dict[str, object]]:
    """Per-batch window declarations, for surfaces with no published index.

    A paginated surface with no index offers nothing to measure coverage
    against. The only evidence the list ended is that asking for the next
    window returned nothing — so a run that received 15 and stopped is
    indistinguishable from one that received 15 because 15 was all there was,
    unless the zero-return is recorded.

    Declared in the staging frontmatter:

        window_requested: 20
        window_returned: 15

    `window_returned` counts ITEMS the source returned, not rows written. One
    item can legitimately yield several rows, so rows >= returned is normal and
    rows < returned is the truncation signal.

    A returned page that holds nothing to record — a pricing page, a legal
    notice — yields no row, and the collector records it as a stop-condition
    keyed by its URL (`no feature: …`). Such a page is accounted for, so it is
    counted beside the rows: a page the staging file lists in `pages:`, that no
    row cites, and that a stop-condition names. Counting rows alone reported
    those windows as underwritten, which was untrue of them.
    """
    stops = stops or set()
    WINDOW_ENDS = ("exhausted", "budget", "error")
    windows: List[Dict[str, object]] = []
    for r in rows_files:
        p = Path(r)
        if not p.exists():
            continue
        parsed = parse_staging(p)
        fm = parsed.frontmatter_raw or {}
        req = _int_or_none(fm.get("window_requested"))
        ret = _int_or_none(fm.get("window_returned"))
        if req is None and ret is None:
            continue

        rows_here = len([x for x in parsed.rows if x.obj is not None])
        if req is None or ret is None:
            findings.append(
                Finding(
                    "window_declaration_incomplete",
                    f"{p.name} declares only one half of its window "
                    f"(window_requested={fm.get('window_requested')!r}, "
                    f"window_returned={fm.get('window_returned')!r}); both are "
                    "needed to tell exhaustion from abandonment",
                    where=str(p),
                )
            )
            continue

        # Non-tautological: the collector declares how many items came back,
        # the checker counts rows independently. Neither side computes both.
        pages = fm.get("pages") if isinstance(fm.get("pages"), list) else []
        cited = {str(x.obj.get("source_url")) for x in parsed.rows if x.obj is not None}
        stopped_here = sorted({str(u) for u in pages} & stops - cited)
        if rows_here + len(stopped_here) < ret:
            findings.append(
                Finding(
                    "window_underwritten",
                    f"{p.name} declares {ret} item(s) returned but holds "
                    f"{rows_here} row(s) and {len(stopped_here)} page(s) closed by a "
                    "stop-condition; items came back that nothing records",
                    where=str(p),
                )
            )
        # WHY a window ended is not derivable from how much it returned.
        # Twelve of twenty asked means the source had twelve, OR the collector
        # took twelve and stopped before it was killed. Those need opposite
        # responses — one ends the subject, the other says resume here — so the
        # collector declares which, and the gate never guesses.
        end = fm.get("window_end")
        if end is None:
            findings.append(
                Finding(
                    "window_end_undeclared",
                    f"{p.name} declares a window but not why it ended. "
                    f"window_end must be one of {', '.join(WINDOW_ENDS)}: a "
                    "short return is not self-explaining",
                    where=str(p),
                )
            )
        elif str(end) not in WINDOW_ENDS:
            findings.append(
                Finding(
                    "window_end_unknown_value",
                    f"{p.name} declares window_end={end!r}; expected one of "
                    f"{', '.join(WINDOW_ENDS)}",
                    where=str(p),
                )
            )
            end = None

        windows.append({
            "file": str(p),
            "requested": req,
            "returned": ret,
            "rows": rows_here,
            "stopped_pages": len(stopped_here),
            "end": str(end) if end is not None else None,
            "offset": _int_or_none(fm.get("window_offset")),
        })
    return windows


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa g4")
    ap.add_argument("--denominator", default=None)
    ap.add_argument("--rows", required=True, nargs="+")
    ap.add_argument("--stops", default=None)
    args = ap.parse_args(argv)

    findings: List[Finding] = []
    inputs: Dict[str, object] = {}
    if args.denominator:
        inputs["denominator"] = input_ref(Path(args.denominator))
    for i, r in enumerate(args.rows):
        inputs[f"rows[{i}]"] = input_ref(Path(r))
    if args.stops:
        inputs["stops"] = input_ref(Path(args.stops))

    windows = read_windows(args.rows, findings, stopped_urls(Path(args.stops) if args.stops else None))

    if args.denominator is None:
        return _window_mode(windows, inputs, findings)

    denom = Path(args.denominator)
    if not denom.exists():
        findings.append(Finding("denominator_missing", f"not found: {denom}"))
        return Verdict(GATE, FAIL, inputs, {"scanned": 0, "failed": 1}, findings), EXIT_FAIL

    items = parse_denominator(denom)
    if not items:
        findings.append(
            Finding(
                "empty_denominator",
                "no index items parsed from the denominator; an empty denominator "
                "cannot certify completeness",
            )
        )
    resolved = disambiguate(items)

    cited_urls: Set[str] = set()
    row_terms: Set[str] = set()
    parent_paths: Set[str] = set()
    total_rows = 0
    for r in args.rows:
        p = Path(r)
        if not p.exists():
            findings.append(Finding("rows_file_missing", f"not found: {p}"))
            continue
        parsed = parse_staging(p)
        for rp in parsed.rows:
            if rp.obj is None:
                continue
            total_rows += 1
            if rp.obj.get("source_url"):
                cited_urls.add(rp.obj["source_url"])
            if rp.obj.get("vendor_term"):
                row_terms.add(_label_key(rp.obj["vendor_term"]))
            if rp.obj.get("parent_path"):
                parent_paths.add(_label_key(rp.obj["parent_path"]))

    stops: Dict[str, str] = {}
    if args.stops:
        sp = Path(args.stops)
        if sp.exists():
            stops, stop_errors = parse_stops(sp)
            for err in stop_errors:
                findings.append(Finding("stop_condition_without_reason", err))
        else:
            findings.append(Finding("stops_file_missing", f"not found: {sp}"))

    stop_keys = {_label_key(k) for k in stops} | set(stops)
    closing = closing_hosts(denom, stops)

    by_url: List[str] = []
    by_name: List[str] = []
    stopped: List[str] = []
    closed: List[str] = []
    without_row: List[str] = []

    for key, (label, url) in sorted(resolved.items()):
        if url in cited_urls:
            by_url.append(url)
            continue
        lk = _label_key(label)
        if lk in row_terms or lk in parent_paths:
            by_name.append(url)
            continue
        if url in stop_keys or lk in stop_keys:
            stopped.append(url)
            continue
        if _host(url) in closing:
            closed.append(url)
            continue
        without_row.append(url)

    for url in without_row:
        findings.append(
            Finding("index_item_without_row", f"no row cites and no stop-condition covers: {url}", where=url)
        )

    counts = {
        # EXISTENCE — what the vendor's own index says is there.
        "existence_index_items": len(resolved),
        "existence_stopped": len(stopped),
        # Items on a host whose surface an operator-approved stop line closed,
        # e.g. `<url> | refused: HTTP 403 (surface help)`. Counted apart, never
        # as evidence.
        "existence_closed_by_surface_line": len(closed),
        "closing_lines": {h: k for h, k in sorted(closing.items())},
        # EVIDENCE — what we have actually sourced. Never blended with the above.
        "evidence_covered_by_url": len(by_url),
        "evidence_covered_by_name": len(by_name),
        "without_row": len(without_row),
        "rows": total_rows,
        "scanned": len(resolved),
        "failed": len(without_row),
    }

    ok = len(without_row) == 0 and not any(
        f.code
        in ("denominator_missing", "rows_file_missing", "stops_file_missing",
            "stop_condition_without_reason", "empty_denominator")
        for f in findings
    )
    return Verdict(GATE, PASS if ok else FAIL, inputs, counts, findings), (
        EXIT_PASS if ok else EXIT_FAIL
    )


def _window_mode(
    windows: List[Dict[str, object]],
    inputs: Dict[str, object],
    findings: List[Finding],
) -> Tuple[Verdict, int]:
    """Completeness for a surface with no denominator.

    Coverage cannot be measured — there is no list to measure against. What CAN
    be established is exhaustion: the collector kept asking until the source ran
    out. Without that, the subject is not incomplete, it is unassessable, and
    saying so out loud is the point. A gate that quietly does not run reads as a
    clean gate.

    A subject parked on a budget stop is a THIRD state, and a legitimate one: a
    5,000-item index cannot be taken in one pass, and a collector that stops
    before it is killed has done the right thing. It is reported with where to
    resume, not as a failure of collection.
    """
    if not windows:
        findings.append(
            Finding(
                "completeness_unassessable",
                "no denominator was given and no batch declares a window, so "
                "there is nothing to measure coverage or exhaustion against. "
                "Capture the subject's own index, or declare window_requested, "
                "window_returned and window_end per batch",
            )
        )
        return (
            Verdict(GATE, FAIL, inputs, {"windows": 0, "scanned": 0, "failed": 1}, findings),
            EXIT_FAIL,
        )

    ordered = sorted(
        windows,
        key=lambda w: (w["offset"] is None, w["offset"] if w["offset"] is not None else 0),
    )

    # Offsets are optional — a mega-menu has no stable index — but where they
    # exist, a chain that skips is a range nobody ever asked for.
    have_offsets = [w for w in ordered if w["offset"] is not None]
    if len(have_offsets) > 1:
        for prev, nxt in zip(have_offsets, have_offsets[1:]):
            expected = int(prev["offset"]) + int(prev["returned"])
            actual = int(nxt["offset"])
            if actual > expected:
                findings.append(
                    Finding(
                        "window_chain_gap",
                        f"items {expected}–{actual - 1} were never requested: "
                        f"{Path(str(prev['file'])).name} covered "
                        f"{prev['offset']}–{expected - 1}, and the next window "
                        f"starts at {actual}",
                        where=str(nxt["file"]),
                    )
                )

    exhausted = [w for w in ordered if w["end"] == "exhausted" or w["returned"] == 0]
    parked = [w for w in ordered if w["end"] == "budget"]
    errored = [w for w in ordered if w["end"] == "error"]

    if not exhausted:
        if parked:
            last = parked[-1]
            resume = (
                f"offset {int(last['offset']) + int(last['returned'])}"
                if last["offset"] is not None
                else f"after the {int(last['returned'])} item(s) in "
                f"{Path(str(last['file'])).name}"
            )
            findings.append(
                Finding(
                    "collection_parked",
                    f"{len(parked)} window(s) stopped on budget and none reached "
                    f"the end of the list. This is a correct place to stop, not a "
                    f"defect — the subject is simply incomplete. Resume at {resume}",
                    where=str(last["file"]),
                )
            )
        else:
            findings.append(
                Finding(
                    "no_exhaustion_evidence",
                    f"{len(ordered)} window(s) declared, none reaching the end of "
                    "the list. A short return is not proof the list ended — it is "
                    "equally consistent with a collector that stopped. Declare "
                    "window_end, and probe once more if it was a budget stop",
                )
            )

    for w in errored:
        findings.append(
            Finding(
                "window_ended_in_error",
                f"{Path(str(w['file'])).name} ended in error after "
                f"{w['returned']} item(s); the range beyond it is unattempted, "
                "not absent",
                where=str(w["file"]),
            )
        )

    counts = {
        "windows": len(ordered),
        "scanned": len(ordered),
        "items_returned": sum(int(w["returned"]) for w in ordered),
        "rows": sum(int(w["rows"]) for w in ordered),
        "reached_end_of_list": len(exhausted),
        "parked_on_budget": len(parked),
        "ended_in_error": len(errored),
        "failed": len(findings),
    }
    ok = bool(exhausted) and not findings
    return Verdict(GATE, PASS if ok else FAIL, inputs, counts, findings), (
        EXIT_PASS if ok else EXIT_FAIL
    )
