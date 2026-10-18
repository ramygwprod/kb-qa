"""Heading coverage — which of a capture's headings no row speaks for.

Advisory, never a failure. Every heading of every captured page is a place the
subject put something; a heading under which no row's quote begins, on a page
no `no feature: …` stop line explains, is a question for a human: a feature
the row-writer missed, or a section that is rightly not a row (an
introduction, a table of contents). The check lists them; it never decides
which.

A heading's section runs from the heading to the next heading of the page,
whatever its level. A row speaks for the section its quote BEGINS in: the
quote is found in the text from that heading to the page's end, and not in the
text from the next heading on. Matching is the grounding gate's — NFKC, quote,
dash and whitespace folding, nothing else. A heading with no text of its own
(the next line is another heading) is counted apart: it holds nothing a row
could quote.

The receipt (`_raw/<batch>/RECEIPT.json`) gives each page's headings with their
capture lines since v6.20.0; a batch captured earlier is reported as not
measured, never as covered.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from .parsing import normalise_for_match, parse_staging
from .stops import LINE_RE, STOPS_NAME


def _no_feature_pages(subject: Path) -> Dict[str, str]:
    """{url: reason} for each stop line keyed by a page — a page stopped for
    any reason is explained as a whole."""
    f = subject / STOPS_NAME
    out: Dict[str, str] = {}
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            m = LINE_RE.match(ln.strip())
            if m:
                out.setdefault(m.group("url"), m.group("reason"))
    return out


def coverage(subject: Path, batch: str) -> dict:
    receipt = subject / "_raw" / batch / "RECEIPT.json"
    if not receipt.exists():
        return {"measured": False, "why": f"no receipt _raw/{batch}/RECEIPT.json"}
    rec = json.loads(receipt.read_text(encoding="utf-8"))
    pages = rec.get("pages") or []
    if pages and any("headings" not in p for p in pages):
        return {"measured": False,
                "why": "the receipt records no heading lines (captured before kbqa 6.20.0)"}
    capture = subject / f"_capture-{batch}.raw.txt"
    if not capture.exists():
        return {"measured": False, "why": f"no capture {capture.name}"}
    lines = capture.read_text(encoding="utf-8").split("\n")

    quotes: Dict[str, List[str]] = {}
    staging = subject / f"_collect-{batch}-staging.md"
    if staging.exists():
        for rp in parse_staging(staging).rows:
            o = rp.obj or {}
            if o.get("source_url") and o.get("source_quote"):
                quotes.setdefault(str(o["source_url"]), []).append(normalise_for_match(str(o["source_quote"])))
    stopped = _no_feature_pages(subject)

    counted = with_row = page_stopped = no_text = 0
    without: List[Dict[str, object]] = []
    for p in pages:
        url, (start, end) = p.get("url"), p.get("lines", [0, 0])
        heads = sorted(p.get("headings") or [], key=lambda h: h["line"])
        last_text = end - 1  # the END marker is not text
        texts = []  # the normalised text from each heading to the page's end
        for h in heads:
            texts.append(normalise_for_match(" ".join(lines[h["line"] - 1:last_text])))
        texts.append("")
        page_quotes = quotes.get(url, [])
        for i, h in enumerate(heads):
            stop = heads[i + 1]["line"] if i + 1 < len(heads) else last_text + 1
            own = [ln for ln in lines[h["line"]:stop - 1] if ln.strip()]
            if not own:
                no_text += 1
                continue
            counted += 1
            if any(q and q in texts[i] and q not in texts[i + 1] for q in page_quotes):
                with_row += 1
            elif url in stopped:
                page_stopped += 1
            else:
                without.append({"url": url, "line": h["line"], "level": h["level"], "text": h["text"]})
    return {"measured": True, "headings": counted, "with_row": with_row,
            "page_stopped": page_stopped, "without_row": len(without),
            "headings_without_text": no_text, "headings_without_row": without}


def summary_line(c: dict) -> str:
    if not c.get("measured"):
        return f"headings: not measured — {c.get('why')}"
    return (f"headings={c['headings']}  with_row={c['with_row']}  page_stopped={c['page_stopped']}  "
            f"without_row={c['without_row']}")


def markdown(c: dict) -> List[str]:
    out = ["## Headings no row speaks for (advisory)", ""]
    if not c.get("measured"):
        out += [f"Not measured: {c.get('why')}.", ""]
        return out
    out.append(f"{c['headings']} headings with text: {c['with_row']} begin a row's quote, "
               f"{c['page_stopped']} are on a page a stop line explains, {c['without_row']} have neither. "
               "Each is a question for a human — a feature the rows missed, or a section that is rightly "
               "not a row. Never a failure.")
    out.append("")
    for h in c["headings_without_row"]:
        out.append(f"- {h['url']} — line {h['line']}: {'#' * int(h['level'])} {h['text']}")
    out.append("")
    return out
