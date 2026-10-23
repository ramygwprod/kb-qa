"""HTML to text, the same way every time — the text a capture holds.

A capture is evidence only if anyone can reproduce it from the bytes that were
served. So this is a fixed rendering, not a summary: every piece of visible
text, in document order, nothing reworded, nothing left out because it looks
like boilerplate. What it does, and nothing more:

- `<head>`, `<script>`, `<style>`, `<noscript>`, `<template>`, `<svg>` and
  `<iframe>` hold no visible text and are skipped;
- whitespace collapses the way a browser collapses it, except inside `<pre>`;
- block elements (headings, paragraphs, list items, table rows, …) and `<br>`
  start a new line; table cells in a row are joined by ` | `;
- a breadcrumb — an element whose `aria-label` or `class` contains
  "breadcrumb" — is written as ONE line, its items joined by ` > `, because a
  row's `parent_path` is copied from that line and a breadcrumb's separators
  are usually drawn by CSS, not written in the page;
- character references are decoded;
- an image's own description — its `alt` text, when it has one and is not
  marked decorative — is written where the image stands, as `[image: <alt>]`
  (in its cell, for a table), because a
  diagram's description is often the only text the page gives about it (since
  v6.21.0). The image itself is not captured.

Links and other attributes are not text and are not rendered.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional, Tuple

SKIP = {"head", "script", "style", "noscript", "template", "svg", "iframe", "object"}
BLOCK = {
    "address", "article", "aside", "blockquote", "body", "caption", "dd", "details",
    "dialog", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "html", "li", "main", "nav",
    "ol", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot", "th",
    "thead", "tr", "ul",
}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
CELL = {"td", "th"}
BREADCRUMB_ITEM = {"li", "a", "span"}
SEPARATOR_ONLY = re.compile(r"^[\s>/›»|·•\-–—]*$")
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


@dataclass
class Rendered:
    """A page's capture text, and where its structure sits in it — kept beside
    the text, never written into it, so quotes still match the page's words."""
    text: str
    headings: List[Tuple[int, int, str]] = field(default_factory=list)  # (line index, level, text)
    breadcrumb: Optional[int] = None  # line index of the breadcrumb line


def _is_breadcrumb(attrs) -> bool:
    for name, value in attrs:
        if name in ("aria-label", "class") and value and "breadcrumb" in value.lower():
            return True
    return False


class _Renderer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: List[str] = []
        self.current: List[str] = []
        self.skip_depth = 0
        self.pre_depth = 0
        self.stack: List[str] = []
        self.in_row = False
        self.cells: List[str] = []
        self.cell: Optional[List[str]] = None
        self.crumb_depth = 0          # depth inside a breadcrumb container
        self.crumbs: List[str] = []
        self.crumb_item: Optional[List[str]] = None
        self.headings: List[Tuple[int, int, str]] = []
        self.breadcrumb: Optional[int] = None

    # ── line handling ──────────────────────────────────────────────────────
    def _text(self, s: str) -> None:
        if self.crumb_depth:
            if self.crumb_item is not None:
                self.crumb_item.append(s)
            else:
                self.crumbs.append(s)
            return
        (self.cell if self.cell is not None else self.current).append(s)

    def _flush(self) -> None:
        raw = "".join(self.current)
        self.current = []
        if self.pre_depth:
            for ln in raw.split("\n"):
                ln = ln.rstrip()
                if ln == "" and (not self.lines or self.lines[-1] == ""):
                    continue  # never two blank lines, never a blank first line
                self.lines.append(ln)
            return
        line = re.sub(r"[ \t\r\n\f\v]+", " ", raw).strip()
        if line:
            self.lines.append(line)

    # ── parser callbacks ──────────────────────────────────────────────────
    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag in SKIP:
                self.skip_depth += 1
            return
        if tag in SKIP:
            self.skip_depth = 1
            return
        if self.crumb_depth:
            if tag not in VOID:
                self.crumb_depth += 1
            if tag in BREADCRUMB_ITEM and self.crumb_item is None:
                self.crumb_item = []
                self.stack.append(f"crumb:{tag}")
            elif tag not in VOID:
                self.stack.append(tag)
            return
        if _is_breadcrumb(attrs):
            self._flush()
            self.crumb_depth = 1
            self.crumbs = []
            self.stack.append(f"breadcrumb:{tag}")
            return
        if tag == "br":
            if self.cell is not None:
                self.cell.append(" ")
            else:
                self._flush()
            return
        if tag == "img":
            self._image(dict(attrs))
            return
        if tag in VOID:
            return
        if tag == "tr":
            self._flush()
            self.in_row = True
            self.cells = []
        elif tag in CELL and self.in_row:
            self.cell = []
        elif tag in BLOCK:
            self._flush()
        if tag == "pre":
            self.pre_depth += 1
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag in SKIP:
                self.skip_depth -= 1
            return
        if self.crumb_depth:
            if tag in VOID:
                return
            self.crumb_depth -= 1
            opened = self.stack.pop() if self.stack else ""
            if opened.startswith("crumb:") and self.crumb_item is not None:
                item = re.sub(r"\s+", " ", "".join(self.crumb_item)).strip()
                if item and not SEPARATOR_ONLY.match(item):
                    self.crumbs.append("\x00" + item)
                self.crumb_item = None
            if self.crumb_depth == 0:
                self._end_breadcrumb()
            return
        if tag in VOID:
            return
        # Close up to the matching open tag; HTML in the wild is not balanced.
        while self.stack:
            opened = self.stack.pop()
            if opened == "pre":
                self._flush()
                self.pre_depth = max(0, self.pre_depth - 1)
            if opened == tag:
                break
        if tag in CELL and self.cell is not None:
            self.cells.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.in_row:
            row = [c for c in self.cells]
            while row and not row[-1]:
                row.pop()
            if any(row):
                self.lines.append(" | ".join(row))
            self.in_row = False
            self.cells = []
        elif tag in BLOCK:
            before = len(self.lines)
            self._flush()
            if tag in HEADINGS and len(self.lines) > before:
                self.headings.append((len(self.lines) - 1, HEADINGS[tag], self.lines[-1]))

    def _image(self, attrs) -> None:
        alt = re.sub(r"\s+", " ", attrs.get("alt") or "").strip()
        if not alt or attrs.get("aria-hidden") == "true" or attrs.get("role") in ("presentation", "none"):
            return  # no description, or one the page marks as decoration
        # In place, like the words around it: a sentence is not split, and an
        # icon in a table cell ("Included") stays in its cell.
        self._text(f" [image: {alt}] ")

    def _end_breadcrumb(self) -> None:
        items = [c[1:] for c in self.crumbs if c.startswith("\x00")]
        if not items:  # a breadcrumb written as plain text with its own separators
            text = re.sub(r"\s+", " ", "".join(c for c in self.crumbs if not c.startswith("\x00"))).strip()
            if text:
                self.lines.append(text)
                self.breadcrumb = len(self.lines) - 1
        else:
            self.lines.append(" > ".join(items))
            self.breadcrumb = len(self.lines) - 1
        self.crumbs = []
        self.crumb_item = None

    def handle_data(self, data):
        if self.skip_depth:
            return
        self._text(data)

    def close(self):
        super().close()
        if self.crumb_depth:
            self.crumb_depth = 0
            self._end_breadcrumb()
        self._flush()
        while self.lines and self.lines[-1] == "":
            self.lines.pop()


def render(html: str) -> Rendered:
    """The capture text of one HTML page, with its headings and breadcrumb
    located. Deterministic: same input, same output."""
    r = _Renderer()
    r.feed(html)
    r.close()
    # A heading in a table header, say, is not counted twice; keep the first.
    seen, heads = set(), []
    for h in r.headings:
        if h[0] not in seen:
            seen.add(h[0])
            heads.append(h)
    return Rendered("\n".join(r.lines), heads, r.breadcrumb)


def html_to_text(html: str) -> str:
    """The capture text of one HTML page. Deterministic: same input, same output."""
    return render(html).text


def visible_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text))
