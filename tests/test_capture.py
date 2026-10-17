"""kbqa capture and kbqa index — collection by code, against a simulated web.

These replace WebFetch, which returned summaries and refused to reproduce more
than a short quote, so no capture written through it could be verbatim — the
first live collection captured nothing. Here a capture is a fixed function of
the served bytes, permission is decided in code from today's robots record, and
the network is never reached: `kbqa.fetch._open` is replaced by a fake web.
"""

import gzip
import io
import json
import urllib.error
from pathlib import Path

import pytest

from kbqa import capture, fetch, index
from kbqa.gates import g3_grounding, g4_completeness
from kbqa.htmltext import html_to_text

DAY = "2026-10-18"
HOST = "docs.example.test"
B = f"docs-{DAY}-w01"

PAGE = """<!doctype html><html><head><title>Webhooks</title><script>var x = 1;</script></head>
<body><nav aria-label="Breadcrumb"><ol><li><a href="/">Docs</a></li><li><a href="/hooks">Webhooks</a></li>
<li>Retries</li></ol></nav>
<main><h1>Retries</h1><p>Failed webhook calls are retried   for up to <b>24 hours</b>.</p>
<p>Admins can change the limit &amp; the interval.</p>
<table><tr><th>Plan</th><th>Retries</th></tr><tr><td>Pro</td><td>5</td></tr></table>
<pre>curl -X POST
  /hooks</pre><style>.x{}</style></main></body></html>"""


class _Resp:
    def __init__(self, url, status, body, ctype):
        self._url, self.status, self._body = url, status, body
        self.headers = {"Content-Type": ctype}

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Web:
    """url -> (status, body, content type[, served url])."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.asked.append(url)
        if url not in self.pages:
            raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
        status, body, ctype, *served = self.pages[url]
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "err", {}, io.BytesIO(b""))
        return _Resp(served[0] if served else url, status, body, ctype)


@pytest.fixture
def subject(tmp_path):
    d = tmp_path / "Example-Co"
    d.mkdir()
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    return d


@pytest.fixture
def web(monkeypatch):
    def install(pages):
        w = Web(pages)
        monkeypatch.setattr(fetch, "_open", w)
        return w
    sleeps = []
    monkeypatch.setattr(fetch, "_sleep", sleeps.append)
    install.sleeps = sleeps
    return install


def run_capture(subject, *urls, batch=B):
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = capture.run(["--out", str(subject), "--batch", batch, "--date", DAY, *sum((["--url", u] for u in urls), [])])
    return code, json.loads(out.getvalue())


def run_index(subject, *args):
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = index.run(["--out", str(subject), "--date", DAY, *args])
    return code, json.loads(out.getvalue())


# ── the rendering ──────────────────────────────────────────────────────────

def test_the_rendering_keeps_every_visible_line_and_nothing_else():
    text = html_to_text(PAGE)
    assert text.splitlines() == [
        "Docs > Webhooks > Retries",
        "Retries",
        "Failed webhook calls are retried for up to 24 hours.",
        "Admins can change the limit & the interval.",
        "Plan | Retries",
        "Pro | 5",
        "curl -X POST",
        "  /hooks",
    ]


def test_the_rendering_is_the_same_every_time():
    assert html_to_text(PAGE) == html_to_text(PAGE)


def test_a_breadcrumb_named_by_class_is_one_line_too():
    html = '<div class="site-breadcrumbs"><a href="/">Help</a> / <a href="/a">Billing</a></div><p>x</p>'
    assert html_to_text(html).splitlines()[0] == "Help > Billing"


# ── capture ────────────────────────────────────────────────────────────────

def test_a_window_is_captured_verbatim_with_its_raw_bytes(subject, web):
    a, b = f"https://{HOST}/hooks/retries", f"https://{HOST}/llms-page.md"
    web({a: (200, PAGE.encode(), "text/html; charset=utf-8"),
         b: (200, b"# Page\nPlain text, kept as served.\n", "text/markdown")})
    code, r = run_capture(subject, a, b)
    assert code == 0, r
    cap = subject / f"_capture-{B}.raw.txt"
    text = cap.read_text()
    assert text.startswith(f"=====BEGIN {a}=====\nDocs > Webhooks > Retries\n")
    assert f"=====END {b}=====" in text and "Plain text, kept as served." in text
    import hashlib
    assert r["sha256"] == hashlib.sha256(cap.read_bytes()).hexdigest()
    raw = subject / r["pages"][0]["raw"]
    assert raw.read_bytes() == PAGE.encode(), "the served bytes are kept unedited"
    assert r["pages"][0]["raw_sha256"] == hashlib.sha256(PAGE.encode()).hexdigest()
    assert (subject / "_raw" / B / "MANIFEST.tsv").exists()


def test_a_quote_from_the_capture_is_grounded_by_g3(subject, web):
    """The point of it: rows written from this capture pass grounding."""
    a = f"https://{HOST}/hooks/retries"
    web({a: (200, PAGE.encode(), "text/html")})
    assert run_capture(subject, a)[0] == 0
    stg = subject / f"_collect-{B}-staging.md"
    stg.write_text(f"---\nbatch: {B}\n---\n```json\n" + json.dumps({
        "id": "example.docs.retries", "source_url": a,
        "source_quote": "Failed webhook calls are retried for up to 24 hours."}) + "\n```\n")
    v, code = g3_grounding.run(["--staging", str(stg), "--capture", str(subject / f"_capture-{B}.raw.txt")])
    assert code == 0, [f.code for f in v.findings]


def test_the_same_bytes_give_the_same_capture(tmp_path, web):
    a = f"https://{HOST}/p"
    shas = []
    for name in ("one", "two"):
        d = tmp_path / name
        d.mkdir()
        (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
        web({a: (200, PAGE.encode(), "text/html")})
        shas.append(run_capture(d, a)[1]["sha256"])
    assert shas[0] == shas[1]


def test_no_robots_record_from_today_means_no_fetch(subject, web):
    (subject / f"_robots-{HOST}-{DAY}.txt").unlink()
    w = web({})
    code, r = run_capture(subject, f"https://{HOST}/p")
    assert code == 1 and "no robots record" in r["refused"]
    assert w.asked == [], "nothing is fetched before permission"


def test_a_path_any_of_our_agents_is_refused_is_not_fetched(subject, web):
    (subject / f"_robots-{HOST}-{DAY}.txt").write_text(
        "User-agent: *\nAllow: /\n\nUser-agent: Claude-User\nDisallow: /private/\n")
    ok, no = f"https://{HOST}/public", f"https://{HOST}/private/x"
    w = web({ok: (200, PAGE.encode(), "text/html"), no: (200, PAGE.encode(), "text/html")})
    code, r = run_capture(subject, ok, no)
    assert code == 0
    assert no not in w.asked
    assert r["excluded"] == [{"url": no, "rule": "/private/"}]
    assert f"- {no} | excluded: robots /private/" in r["stop_lines_to_add"]


def test_the_longest_rule_wins_and_allow_wins_a_tie(subject, web):
    (subject / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nDisallow: /docs/\nAllow: /docs/public/\n")
    rb = fetch.robots_for(subject, HOST, DAY)
    assert rb.check(f"https://{HOST}/docs/public/a") == (True, None)
    assert rb.check(f"https://{HOST}/docs/secret")[0] is False
    (subject / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nDisallow: /*.pdf$\n")
    rb = fetch.robots_for(subject, HOST, DAY)
    assert rb.check(f"https://{HOST}/a/b.pdf")[0] is False and rb.check(f"https://{HOST}/a/b.pdf?x")[0] is True


def test_a_site_wide_refusal_fetches_nothing(subject, web):
    (subject / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: ClaudeBot\nDisallow: /\n")
    w = web({f"https://{HOST}/p": (200, PAGE.encode(), "text/html")})
    code, r = run_capture(subject, f"https://{HOST}/p")
    assert code == 1 and w.asked == []
    assert r["stop_lines_to_add"] == [f"- https://{HOST}/p | refused: robots"]


def test_the_crawl_delay_is_honoured_between_requests(subject, web):
    (subject / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\nCrawl-delay: 7\n")
    web({f"https://{HOST}/{n}": (200, PAGE.encode(), "text/html") for n in "abc"})
    assert run_capture(subject, *(f"https://{HOST}/{n}" for n in "abc"))[0] == 0
    assert len(web.sleeps) == 2 and all(0 < s <= 7 for s in web.sleeps)


def test_throttling_ends_the_window_there(subject, web):
    a, b, c = (f"https://{HOST}/{n}" for n in "abc")
    w = web({a: (200, PAGE.encode(), "text/html"), b: (429, b"", "text/html"), c: (200, PAGE.encode(), "text/html")})
    code, r = run_capture(subject, a, b, c)
    assert code == 0 and [p["url"] for p in r["pages"]] == [a]
    assert r["stopped"] == {"reason": "throttled", "not_attempted": [b, c]}
    assert c not in w.asked, "never retried another way, never continued past it"


def test_a_redirect_on_the_host_is_captured_under_the_served_url(subject, web):
    a, served = f"https://{HOST}/old", f"https://{HOST}/new"
    web({a: (200, PAGE.encode(), "text/html", served)})
    code, r = run_capture(subject, a)
    assert code == 0 and r["redirects"] == [{"requested": a, "served": served}]
    assert f"=====BEGIN {served}=====" in (subject / f"_capture-{B}.raw.txt").read_text()


def test_a_redirect_off_the_host_is_not_captured(subject, web):
    a = f"https://{HOST}/out"
    web({a: (200, PAGE.encode(), "text/html", "https://other.test/x")})
    code, r = run_capture(subject, a)
    assert code == 1 and r["capture"] is None
    assert r["stop_lines_to_add"] == [f"- {a} | third-party host: other.test"]


def test_a_javascript_shell_is_not_captured_and_says_so(subject, web):
    a = f"https://{HOST}/app"
    web({a: (200, b'<html><body><div id="root"></div><script src="/app.js"></script></body></html>', "text/html")})
    code, r = run_capture(subject, a)
    assert code == 1 and "js-only" in r["failures"][0]["reason"]
    assert r["stop_lines_to_add"] == [f"- {a} | js-only: not readable"]


def test_a_pdf_is_not_captured(subject, web):
    a = f"https://{HOST}/guide.pdf"
    web({a: (200, b"%PDF-1.7", "application/pdf")})
    code, r = run_capture(subject, a)
    assert code == 1 and "not a page" in r["failures"][0]["reason"]


def test_a_batch_name_is_never_reused(subject, web):
    a = f"https://{HOST}/p"
    web({a: (200, PAGE.encode(), "text/html")})
    assert run_capture(subject, a)[0] == 0
    before = (subject / f"_capture-{B}.raw.txt").read_bytes()
    code, r = run_capture(subject, a)
    assert code == 1 and "never reused" in r["refused"]
    assert (subject / f"_capture-{B}.raw.txt").read_bytes() == before


def test_a_batch_must_carry_todays_date(subject, web):
    web({})
    code, r = run_capture(subject, f"https://{HOST}/p", batch="docs-2026-01-01-w01")
    assert code == 1 and "today's access date" in r["refused"]


# ── index ──────────────────────────────────────────────────────────────────

LLMS = b"""# Example
> The docs.

## Guides
- [Getting started](https://docs.example.test/start): first steps
- [Webhooks](https://docs.example.test/hooks)

Some prose that is not an item.
"""


def test_llms_txt_becomes_the_denominator_line_for_line(subject, web):
    web({f"https://{HOST}/llms.txt": (200, LLMS, "text/plain")})
    code, r = run_index(subject, "--surface", "docs", "--rung", "1", "--url", f"https://{HOST}/llms.txt")
    assert code == 0, r
    den = subject / f"_denominator-docs-{DAY}.md"
    assert den.read_text().splitlines() == [
        f"Index: docs, rung 1 — https://{HOST}/llms.txt",
        "- [Getting started](https://docs.example.test/start): first steps",
        "- [Webhooks](https://docs.example.test/hooks)",
    ]
    assert [u for _, u in g4_completeness.parse_denominator(den)] == [
        "https://docs.example.test/start", "https://docs.example.test/hooks"]


def _sitemap(*locs, index=False):
    tag, item = ("sitemapindex", "sitemap") if index else ("urlset", "url")
    body = "".join(f"<{item}><loc>{l}</loc></{item}>" for l in locs)
    return f'<?xml version="1.0"?><{tag} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</{tag}>'.encode()


def test_a_sitemap_index_is_followed_into_its_sitemaps(subject, web):
    h = "help.example.test"
    (subject / f"_robots-{h}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    web({f"https://{h}/sitemap.xml": (200, _sitemap(f"https://{h}/s1.xml.gz", f"https://{h}/s2.xml", index=True), "application/xml"),
         f"https://{h}/s1.xml.gz": (200, gzip.compress(_sitemap(f"https://{h}/hc/en-us/a", f"https://{h}/hc/de/a")), "application/gzip"),
         f"https://{h}/s2.xml": (200, _sitemap(f"https://{h}/hc/en-us/b"), "application/xml")})
    code, r = run_index(subject, "--surface", "help", "--rung", "3", "--url", f"https://{h}/sitemap.xml",
                        "--path-prefix", "/hc/en-us/")
    assert code == 0, r
    lines = (subject / f"_denominator-help-{DAY}.md").read_text().splitlines()
    assert "items whose path starts with /hc/en-us/ (2 of 3; scope approved by the operator)" in lines[0]
    assert lines[1:] == [f"https://{h}/hc/en-us/a", f"https://{h}/hc/en-us/b"]
    assert len(r["sources"]) == 3, "every sitemap read is kept as raw evidence"


def test_an_html_index_lists_its_same_host_links_in_page_order(subject, web):
    html = b"""<nav><a href="/a">Alpha</a> <a href="/b#top">Beta</a> <a href="/a">Alpha again</a>
    <a href="https://other.test/x">Off</a> <a href="mailto:x@y">Mail</a></nav>"""
    web({f"https://{HOST}/": (200, html, "text/html")})
    code, r = run_index(subject, "--surface", "docs", "--rung", "4", "--url", f"https://{HOST}/", "--html")
    assert code == 0, r
    assert (subject / f"_denominator-docs-{DAY}.md").read_text().splitlines()[1:] == [
        f"- [Alpha](https://{HOST}/a)", f"- [Beta](https://{HOST}/b)"]


def test_an_index_robots_excludes_gives_a_surface_stop_line(subject, web):
    (subject / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nDisallow: /llms.txt\n")
    w = web({})
    code, r = run_index(subject, "--surface", "docs", "--rung", "1", "--url", f"https://{HOST}/llms.txt")
    assert code == 1 and w.asked == []
    assert r["stop_lines_to_add"] == [f"- https://{HOST}/llms.txt | excluded: robots /llms.txt (surface docs)"]


def test_a_denominator_is_written_once(subject, web):
    web({f"https://{HOST}/llms.txt": (200, LLMS, "text/plain")})
    args = ("--surface", "docs", "--rung", "1", "--url", f"https://{HOST}/llms.txt")
    assert run_index(subject, *args)[0] == 0
    code, r = run_index(subject, *args)
    assert code == 1 and "written once" in r["refused"]


# ── windows sliced by code ─────────────────────────────────────────────────

def _den(subject, n=5):
    den = subject / f"_denominator-docs-{DAY}.md"
    den.write_text(f"Index: docs, rung 1 — https://{HOST}/llms.txt\n"
                   + "".join(f"- [P{i}](https://{HOST}/p{i})\n" for i in range(1, n + 1)))
    return den


def _pages(n=5, size=1):
    body = lambda i: f"<html><body><p>{('Page %d says something useful. ' % i) * size}</p></body></html>".encode()
    return {f"https://{HOST}/p{i}": (200, body(i), "text/html") for i in range(1, n + 1)}


def _window(subject, w, *args):
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = capture.run(["--out", str(subject), "--batch", f"docs-{DAY}-w{w:02d}", "--date", DAY, *args])
    return code, json.loads(out.getvalue())


def test_windows_walk_the_selection_until_code_says_exhausted(subject, web):
    den = _den(subject)
    web(_pages())
    seen, offset, ends = [], 0, []
    for w in (1, 2, 3):
        code, r = _window(subject, w, "--denominator", str(den), "--offset", str(offset), "--max-pages", "2")
        assert code == 0, r
        seen += [p["url"] for p in r["pages"]]
        ends.append((r["window_requested"], r["remaining"], r["window_end"]))
        offset = r["next_offset"]
    assert seen == [f"https://{HOST}/p{i}" for i in range(1, 6)]
    assert ends == [(2, 3, "budget"), (2, 1, "budget"), (1, 0, "exhausted")]
    code, r = _window(subject, 4, "--denominator", str(den), "--offset", str(offset))
    assert code == 1 and "exhausted" in r["refused"]


def test_a_selection_takes_only_the_approved_lines_in_order(subject, web):
    den = _den(subject)
    w = web(_pages())
    code, r = _window(subject, 1, "--denominator", str(den), "--select", "6,2-3")
    assert code == 0 and r["selected_items"] == 3 and r["window_end"] == "exhausted"
    assert [p["url"] for p in r["pages"]] == [f"https://{HOST}/p5", f"https://{HOST}/p1", f"https://{HOST}/p2"]
    assert f"https://{HOST}/p3" not in w.asked


def test_a_selection_naming_a_line_with_no_item_is_refused(subject, web):
    den = _den(subject)
    web(_pages())
    code, r = _window(subject, 1, "--denominator", str(den), "--select", "1-2")
    assert code == 1 and "hold no item: [1]" in r["refused"]


def test_the_text_budget_ends_a_window_after_the_page_that_passes_it(subject, web):
    den = _den(subject)
    web(_pages(size=40))  # about 1,300 characters a page
    code, r = _window(subject, 1, "--denominator", str(den), "--max-chars", "2000")
    assert code == 0 and len(r["pages"]) == 2
    assert r["stopped"] == {"reason": "budget: max-chars"} and r["next_offset"] == 2 and r["window_end"] == "budget"


def test_a_page_larger_than_the_budget_is_captured_alone(subject, web):
    den = _den(subject, n=2)
    web(_pages(n=2, size=200))
    code, r = _window(subject, 1, "--denominator", str(den), "--max-chars", "1000")
    assert code == 0 and len(r["pages"]) == 1 and r["pages"][0]["oversize"] is True
    assert r["remaining"] == 1


def test_each_page_can_be_read_alone_by_its_line_range(subject, web):
    den = _den(subject, n=3)
    web(_pages(n=3))
    code, r = _window(subject, 1, "--denominator", str(den))
    lines = (subject / f"_capture-docs-{DAY}-w01.raw.txt").read_text().splitlines()
    for p in r["pages"]:
        a, b = p["lines"]
        assert lines[a - 1] == f"=====BEGIN {p['url']}=====" and lines[b - 1] == f"=====END {p['url']}====="


def test_index_summarises_the_denominator_by_section(subject, web):
    h = "help.example.test"
    (subject / f"_robots-{h}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    locs = [f"https://{h}/hc/en-us/a{i}" for i in range(3)] + [f"https://{h}/blog/b{i}" for i in range(2)]
    web({f"https://{h}/sitemap.xml": (200, _sitemap(*locs), "application/xml")})
    code, r = run_index(subject, "--surface", "help", "--rung", "3", "--url", f"https://{h}/sitemap.xml")
    assert code == 0
    assert r["sections"] == [{"section": f"{h}/hc/en-us", "items": 3, "lines": "2-4"},
                             {"section": f"{h}/blog/b0", "items": 1, "lines": "5"},
                             {"section": f"{h}/blog/b1", "items": 1, "lines": "6"}]


def test_a_tiny_page_without_scripts_is_captured_not_called_a_shell(subject, web):
    a = f"https://{HOST}/tiny"
    web({a: (200, b"<html><body><p>Coming soon.</p></body></html>", "text/html")})
    code, r = run_capture(subject, a)
    assert code == 0 and r["pages"][0]["text_chars"] < 50


# ── a long page is read in parts, each with its context ────────────────────

def _long_page(sections=5, paras=20):
    body = "".join(
        f"<h2>Section {s}</h2>" + "".join(f"<p>Section {s} paragraph {p} explains one more thing about it in plain words.</p>"
                                           for p in range(paras))
        for s in range(1, sections + 1))
    return (f'<html><body><nav aria-label="breadcrumb"><ol><li>Docs</li><li>Guide</li></ol></nav>'
            f"<h1>The Guide</h1>{body}</body></html>").encode()


def test_a_long_page_is_split_at_headings_and_every_line_is_read_once(subject, web):
    a = f"https://{HOST}/guide"
    web({a: (200, _long_page(), "text/html")})
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert capture.run(["--out", str(subject), "--batch", B, "--date", DAY, "--url", a,
                            "--part-chars", "4000"]) == 0
    page = json.loads(out.getvalue())["pages"][0]
    lines = (subject / f"_capture-{B}.raw.txt").read_text().splitlines()
    parts = page["parts"]
    assert len(parts) > 1
    # own lines: contiguous, no gap, no overlap, exactly the page's text lines
    first_text, last_text = page["lines"][0] + 1, page["lines"][1] - 1
    assert parts[0]["lines"][0] == first_text and parts[-1]["lines"][1] == last_text
    for prev, nxt in zip(parts, parts[1:]):
        assert nxt["lines"][0] == prev["lines"][1] + 1
    # every later part starts on a heading, keeps its context, and overlaps a little
    for pt in parts[1:]:
        assert lines[pt["lines"][0] - 1].startswith("Section ") and "paragraph" not in lines[pt["lines"][0] - 1]
        assert pt["breadcrumb"] == "Docs > Guide"
        assert pt["headings"] == ["The Guide"]
        assert 0 < pt["lines"][0] - pt["read_from"] <= 3


def test_a_section_with_no_headings_is_cut_at_a_line_end(subject, web):
    a = f"https://{HOST}/flat"
    flat = "<html><body>" + "".join(f"<p>Line {i} of a page with no headings at all.</p>" for i in range(400)) + "</body></html>"
    web({a: (200, flat.encode(), "text/html")})
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert capture.run(["--out", str(subject), "--batch", B, "--date", DAY, "--url", a,
                            "--part-chars", "3000"]) == 0
    parts = json.loads(out.getvalue())["pages"][0]["parts"]
    lines = (subject / f"_capture-{B}.raw.txt").read_text().splitlines()
    assert len(parts) > 1
    for pt in parts:
        own = lines[pt["lines"][0] - 1: pt["lines"][1]]
        assert all(ln.startswith("Line ") for ln in own), "a part never begins or ends inside a line"
        assert sum(len(x) + 1 for x in own) <= 3000


def test_an_ordinary_page_is_one_part(subject, web):
    a = f"https://{HOST}/hooks/retries"
    web({a: (200, PAGE.encode(), "text/html")})
    code, r = run_capture(subject, a)
    page = r["pages"][0]
    assert page["parts"] == [{"lines": [page["lines"][0] + 1, page["lines"][1] - 1],
                              "read_from": page["lines"][0] + 1,
                              "breadcrumb": "Docs > Webhooks > Retries", "headings": []}]


# ── the APQC outline ───────────────────────────────────────────────────────

def test_the_element_outline_gives_each_group_its_line_ranges(tmp_path):
    from kbqa import elements
    rows = [("1.0", "Develop strategy"), ("1.1", "Define the concept"), ("1.1.1", "Assess"),
            ("1.2", "Develop the strategy"), ("1.2.1", "Plan"), ("2.0", "Develop products"),
            ("2.1", "Manage products"), ("2.1.1", "Design")]
    lst = tmp_path / "apqc.jsonl"
    lst.write_text("".join(json.dumps({"pcf_id": str(10000 + i), "hierarchy_id": h, "name": n}) + "\n"
                           for i, (h, n) in enumerate(rows)))
    assert elements.run(["--outline", str(lst)]) == 0
    text = (tmp_path / "apqc.outline.md").read_text()
    assert "| 1.0 | Develop strategy | 1-5 |" in text
    assert "| 1.1 | Define the concept | 2-3 |" in text
    assert "| 1.2 | Develop the strategy | 4-5 |" in text
    assert "| 2.1 | Manage products | 7-8 |" in text
    import hashlib
    assert hashlib.sha256(lst.read_bytes()).hexdigest() in text.splitlines()[0]
    first = text
    assert elements.run(["--outline", str(lst)]) == 0
    assert (tmp_path / "apqc.outline.md").read_text() == first, "the same list gives the same outline"
