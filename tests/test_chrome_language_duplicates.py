"""v6.21.0 — the capture keeps evidence complete and reads nothing twice.

The operator's rulings of 2026-10-22:
- a site's header and footer are collected once, not with every page;
- when a page exists in English, its other-language copies are not collected;
and from the architecture review: the same text under a second URL is one page,
and an image's own description (its alt text) is kept.
"""

import json
from pathlib import Path

import pytest

from kbqa import language
from kbqa.htmltext import render

from test_capture import DAY, HOST, _cap, _den, run_index, subject, web  # noqa: F401 (fixtures)

NAV = '<header><nav><a href="/">Home</a><a href="/p">Product</a><a href="/d">Docs</a></nav><p>Sign in</p></header>'
FOOT = '<footer><p>Terms</p><p>Privacy</p><p>© Example</p></footer>'


def page(body: str, crumb: str = "", chrome: bool = True) -> tuple:
    crumb_html = f'<nav aria-label="breadcrumb"><a>Docs</a><a>{crumb}</a></nav>' if crumb else ""
    html = (f"<html><body>{NAV if chrome else ''}{crumb_html}<main>{body}</main>"
            f"{FOOT if chrome else ''}</body></html>")
    return (200, html.encode(), "text/html")


def _pages(n, chrome=True):
    return {f"https://{HOST}/p{i}": page(f"<h1>Topic {i}</h1><p>Body of page {i}.</p>", f"Topic {i}", chrome)
            for i in range(1, n + 1)}


# ── header and footer, once ──────────────────────────────────────────────────

def test_header_and_footer_are_kept_once_and_taken_off_every_page(subject, web):
    web(_pages(4))
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=4)))
    assert code == 0
    text = (subject / f"_capture-{r['batch']}.raw.txt").read_text()
    assert "Sign in" not in text and "Privacy" not in text, "chrome is not on any page"
    assert text.count("Body of page") == 4
    files = {c["edge"]: c for c in r["chrome"]}
    assert set(files) == {"header", "footer"}
    assert (subject / files["header"]["file"]).read_text() == "HomeProductDocs\nSign in"  # adjacent links render as one line
    assert (subject / files["footer"]["file"]).read_text() == "Terms\nPrivacy\n© Example"
    for p in r["pages"]:
        assert p["chrome"]["header_lines"] == 2 and p["chrome"]["footer_lines"] == 3


def test_the_full_text_is_chrome_plus_capture_plus_chrome(subject, web):
    pages = _pages(3)
    web(pages)
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=3)))
    lines = (subject / f"_capture-{r['batch']}.raw.txt").read_text().split("\n")
    for p in r["pages"]:
        body = lines[p["lines"][0]:p["lines"][1] - 1]  # between the markers
        head = (subject / p["chrome"]["header"]).read_text().split("\n")
        foot = (subject / p["chrome"]["footer"]).read_text().split("\n")
        assert head + body + foot == render(pages[p["url"]][1].decode()).text.split("\n")


def test_the_breadcrumb_and_headings_stay_on_the_page(subject, web):
    web(_pages(3))
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=3)))
    lines = (subject / f"_capture-{r['batch']}.raw.txt").read_text().split("\n")
    for p in r["pages"]:
        assert lines[p["lines"][0]] .startswith("Docs > Topic"), "the breadcrumb opens the page"
        assert p["parts"][0]["breadcrumb"].startswith("Docs > Topic")
        for h in p["headings"]:
            assert lines[h["line"] - 1] == h["text"]


def test_a_later_window_with_one_page_uses_the_kept_chrome(subject, web):
    web(_pages(5))
    _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=5)), "--max-pages", "4")
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=5)), "--resume")
    assert code == 0 and len(r["pages"]) == 1
    assert r["pages"][0]["chrome"]["header_lines"] == 2, "one page is too few to detect, but the kept chrome applies"


def test_too_few_pages_leave_the_text_whole(subject, web):
    web(_pages(2))
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=2)))
    assert r["chrome"] == [] and "Sign in" in (subject / f"_capture-{r['batch']}.raw.txt").read_text()


def test_a_page_that_is_only_chrome_keeps_its_text(subject, web):
    pages = _pages(3)
    pages[f"https://{HOST}/p4"] = (200, f"<html><body>{NAV}{FOOT}</body></html>".encode(), "text/html")
    web(pages)
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=4)))
    last = next(p for p in r["pages"] if p["url"].endswith("/p4"))
    assert last["chrome"]["header_lines"] + last["chrome"]["footer_lines"] < 5, "never the whole page"


# ── the same text under another URL ──────────────────────────────────────────

def test_the_same_text_under_a_second_url_is_a_copy_not_a_page(subject, web):
    pages = _pages(3, chrome=False)
    pages[f"https://{HOST}/p4"] = pages[f"https://{HOST}/p1"]
    web(pages)
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=4)))
    assert [p["url"] for p in r["pages"]] == [f"https://{HOST}/p{i}" for i in (1, 2, 3)]
    assert r["duplicates"][0]["url"] == f"https://{HOST}/p4"
    assert r["duplicates"][0]["same_text_as"] == f"https://{HOST}/p1"
    assert f"- https://{HOST}/p4 | no feature: same text as https://{HOST}/p1" in r["stop_lines_to_add"]


def test_a_copy_of_a_page_from_an_earlier_window_is_found(subject, web):
    pages = _pages(3, chrome=False)
    pages[f"https://{HOST}/p4"] = pages[f"https://{HOST}/p2"]
    web(pages)
    _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=4)), "--max-pages", "3")
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=4)), "--resume")
    assert r["pages"] == [] and r["duplicates"][0]["same_text_as"] == f"https://{HOST}/p2"


# ── English is enough ────────────────────────────────────────────────────────

H = "help.example.test"


def _llms(urls):
    return ("# Help\n\n" + "".join(f"- [{u.rsplit('/', 1)[-1]}]({u})\n" for u in urls)).encode()


@pytest.fixture
def help_host(subject):
    (subject / f"_robots-{H}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    return subject


def test_language_copies_with_an_english_page_are_left_out_and_listed(help_host, web):
    eng = [f"https://{H}/a/{i}" for i in range(3)]
    fr = [f"https://{H}/fr/a/{i}" for i in range(3)]
    web({f"https://{H}/llms.txt": (200, _llms(eng + fr + [f"https://{H}/fr/only"]), "text/plain")})
    code, r = run_index(help_host, "--surface", "help", "--rung", "1", "--url", f"https://{H}/llms.txt")
    assert code == 0, r
    lines = (help_host / f"_denominator-help-{DAY}.md").read_text().splitlines()
    assert "3 language copies left out" in lines[0]
    assert not any("/fr/a/" in ln for ln in lines[1:])
    assert any(ln.endswith(f"(https://{H}/fr/only)") for ln in lines[1:]), "no English page: kept"
    tsv = (help_host / r["language_copies"]["file"]).read_text().splitlines()
    assert tsv[1] == f"https://{H}/fr/a/0\thttps://{H}/a/0"


def test_a_lone_path_that_looks_like_a_language_is_kept(help_host, web):
    urls = [f"https://{H}/it/setup", f"https://{H}/setup", f"https://{H}/other"]
    web({f"https://{H}/llms.txt": (200, _llms(urls), "text/plain")})
    code, r = run_index(help_host, "--surface", "help", "--rung", "1", "--url", f"https://{H}/llms.txt")
    assert "language_copies" not in r and r["items"] == 3


def test_all_languages_keeps_every_copy(help_host, web):
    urls = [f"https://{H}/a/{i}" for i in range(3)] + [f"https://{H}/de/a/{i}" for i in range(3)]
    web({f"https://{H}/llms.txt": (200, _llms(urls), "text/plain")})
    code, r = run_index(help_host, "--surface", "help", "--rung", "1", "--url", f"https://{H}/llms.txt",
                        "--all-languages")
    assert r["items"] == 6 and "language_copies" not in r


def test_the_sitemaps_own_hreflang_names_the_english_page(help_host, web):
    xml = (f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           f'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
           f'<url><loc>https://{H}/start</loc>'
           f'<xhtml:link rel="alternate" hreflang="en" href="https://{H}/start"/>'
           f'<xhtml:link rel="alternate" hreflang="ja" href="https://{H}/hajime"/></url>'
           f'<url><loc>https://{H}/hajime</loc>'
           f'<xhtml:link rel="alternate" hreflang="ja" href="https://{H}/hajime"/>'
           f'<xhtml:link rel="alternate" hreflang="en" href="https://{H}/start"/></url>'
           f'</urlset>').encode()
    web({f"https://{H}/sitemap.xml": (200, xml, "application/xml")})
    code, r = run_index(help_host, "--surface", "help", "--rung", "3", "--url", f"https://{H}/sitemap.xml")
    assert code == 0 and r["items"] == 1 and r["language_copies"]["left_out"] == 1


def test_an_english_page_is_never_a_copy():
    assert language.copies([f"https://{H}/en-gb/a/{i}" for i in range(3)]
                           + [f"https://{H}/en/a/{i}" for i in range(3)]) == {}


# ── an image's own description ───────────────────────────────────────────────

def test_an_images_alt_text_is_kept_in_place():
    text = render('<p>Calls <img alt="routing diagram"> flow.</p><img alt=""><img alt="x" aria-hidden="true">'
                  '<table><tr><td><img alt="Included"></td><td>SSO</td></tr></table>').text
    assert text.split("\n") == ["Calls [image: routing diagram] flow.", "[image: Included] | SSO"]


def test_a_breadcrumb_shared_by_every_page_is_never_chrome(subject, web):
    web({f"https://{HOST}/p{i}": page(f"<h1>Topic {i}</h1><p>Body {i}.</p>", "Guides") for i in range(1, 5)})
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=4)))
    lines = (subject / f"_capture-{r['batch']}.raw.txt").read_text().split("\n")
    for p in r["pages"]:
        assert lines[p["lines"][0]] == "Docs > Guides", "the breadcrumb opens every page's block"
        assert p["chrome"]["header_lines"] == 2


def test_a_last_window_of_copies_still_finishes_the_surface(subject, web):
    pages = _pages(3, chrome=False)
    pages[f"https://{HOST}/p4"] = pages[f"https://{HOST}/p1"]
    web(pages)
    _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=4)), "--max-pages", "3")
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(_den(subject, n=4)), "--resume")
    assert code == 0, "a window of copies did its work"
    assert r["window_end"] == "exhausted" and r["capture"] is None
    assert r["stop_lines_to_add"] == [f"- https://{HOST}/p4 | no feature: same text as https://{HOST}/p1"]
    import contextlib, io
    from kbqa import capture
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        capture.run(["--out", str(subject), "--date", DAY, "--surface", "docs", "--status"])
    assert json.loads(out.getvalue())["exhausted"] is True
