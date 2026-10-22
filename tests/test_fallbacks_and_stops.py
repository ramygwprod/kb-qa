"""v6.18.0 — what the first full live run exposed, each guarded here.

The receipt is a file, so no agent retypes window fields (#6). Stop lines come
from one vocabulary in code and are added atomically (#11, #2c). A TLS failure
is final (#10). A run that crosses midnight runs G0 itself (#3, in
test_capture). A same-day correction supersedes a denominator (#1). A selection
can be made by path (#5). `--status --files` is an inventory (#4). An llms.txt's
own headings are its sections (#12). The plan probes each host (#24). A host
refusing our fetcher is tried through its own copy, and every failure carries a
next step from code (#2, the fallback tree). A story's role is its `role` (#9).
"""

import io
import json
import re
import ssl
import threading
import urllib.error
from pathlib import Path

import pytest

from kbqa import capture, fetch, index, stops
from kbqa.gates import g4_completeness, mapcheck, surfaces

from test_capture import DAY, HOST, OK, PAGE, SeqWeb, _cap, _den, ok_page, run_index

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def subject(tmp_path):
    d = tmp_path / "Example-Co"
    d.mkdir()
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    return d


@pytest.fixture
def seqweb(monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetch, "_sleep", sleeps.append)

    def install(pages):
        w = SeqWeb(pages)
        monkeypatch.setattr(fetch, "_open", w)
        return w
    install.sleeps = sleeps
    return install


MD = (200, b"# Retries\n\nFailed webhook calls are retried for up to 24 hours, as the guide says.\n",
      "text/markdown; charset=utf-8")


# ── #6 the receipt is a file ─────────────────────────────────────────────────

def test_the_receipt_is_written_beside_the_window_state_and_matches_the_output(subject, seqweb):
    den = _den(subject, n=2)
    seqweb({f"https://{HOST}/p1": OK, f"https://{HOST}/p2": OK})
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(den))
    assert code == 0
    on_disk = json.loads((subject / "_raw" / r["batch"] / "RECEIPT.json").read_text())
    assert on_disk == r, "the file is the receipt — the row-writer reads it instead of a retyped copy"
    for k in ("window_offset", "window_requested", "window_returned", "window_end", "sha256", "access_date"):
        assert k in on_disk
    assert on_disk["receipt"] == f"_raw/{r['batch']}/RECEIPT.json"


def test_a_window_that_captured_nothing_still_has_its_receipt(subject, seqweb):
    den = _den(subject, n=1)
    seqweb({f"https://{HOST}/p1": (404, b"", "")})
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(den))
    assert code == 1 and r["window_end"] == "error"
    assert json.loads((subject / "_raw" / r["batch"] / "RECEIPT.json").read_text()) == r


# ── #11 / #2c one vocabulary, one atomic add ─────────────────────────────────

def test_every_reason_reads_as_itself_and_nothing_else_passes():
    good = ["- https://x.test/ | surface help not published: the menu links no help centre",
            "- https://x.test/a | refused: robots",
            "- https://x.test/a | refused: HTTP 403",
            "- https://x.test/a | refused: HTTP 403 (surface help)",
            "- https://x.test/a | excluded: robots /private/",
            "- https://x.test/a | js-only: not readable (surface docs)",
            "- https://x.test/a | gated: login",
            "- https://x.test/a | third-party host: other.test",
            "- https://x.test/a.pdf | not approved: pdf",
            "- https://x.test/a | unreachable: HTTP 404",
            "- https://x.test/a | unreachable: URLError: timed out in 3 runs",
            "- https://x.test/a | no feature: pricing page"]
    for ln in good:
        stops.parse_line(ln)
    bad = ["- https://x.test/a | unreachable", "- https://x.test/a | refused: HTTP 500",
           "- https://x.test/a | host 403 (bot protection)", "https://x.test/a | gated: login",
           "- /relative | gated: login", "- https://x.test/a | no feature: x (surface help) (surface docs)",
           "- https://x.test/a | not approved: pdf (surface help)"]
    for ln in bad:
        with pytest.raises(stops.StopLineError):
            stops.parse_line(ln)


def test_a_closing_suffix_is_read_as_the_surface_it_closes():
    assert stops.parse_line("- https://x.test/a | unreachable: HTTP 404 (surface help)")[3] == "help"
    with pytest.raises(stops.StopLineError):
        stops.parse_line("- https://x.test/a | no feature: blog (surface help)")


def test_stop_add_appends_once_and_refuses_an_unknown_reason(tmp_path, capsys):
    (tmp_path / "_stop-conditions.md").write_text("---\nnote: kept\n---\n- https://x.test/a | gated: login")
    assert stops.run(["add", str(tmp_path), "- https://x.test/b | no feature: pricing page"]) == 0
    assert stops.run(["add", str(tmp_path), "- https://x.test/b | no feature: pricing page"]) == 0
    assert "already recorded" in capsys.readouterr().out
    assert stops.run(["add", str(tmp_path), "- https://x.test/c | host 403 (bot protection)"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert "not in the vocabulary" in out["refused"] and out["next_step"] == "operator"
    assert (tmp_path / "_stop-conditions.md").read_text() == (
        "---\nnote: kept\n---\n- https://x.test/a | gated: login\n- https://x.test/b | no feature: pricing page\n")


def test_concurrent_adds_lose_no_line(tmp_path):
    lines = [f"- https://x.test/p{i} | no feature: page {i}" for i in range(200)]
    threads = [threading.Thread(target=stops.add, args=(tmp_path, ln)) for ln in lines]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got = (tmp_path / "_stop-conditions.md").read_text().splitlines()
    assert sorted(got) == sorted(lines)


def test_stop_add_waits_for_a_lock_another_writer_holds(tmp_path):
    """The append happens under the file's exclusive lock — a fetcher adding a
    line while another holds the file waits, so neither line is lost."""
    import fcntl
    import time
    f = tmp_path / "_stop-conditions.md"
    f.write_text("- https://x.test/a | gated: login\n")
    holder = open(f, "a+")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    t = threading.Thread(target=stops.add, args=(tmp_path, "- https://x.test/b | gated: login"))
    t.start()
    time.sleep(0.3)
    assert "x.test/b" not in f.read_text(), "the add did not wait for the lock"
    fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
    holder.close()
    t.join(5)
    assert f.read_text().splitlines() == ["- https://x.test/a | gated: login", "- https://x.test/b | gated: login"]


FETCHER = (ROOT / "agents" / "kbqa-fetcher.md").read_text(encoding="utf-8")


def test_the_fetchers_reason_table_is_the_vocabulary():
    """#2c: v6.17.1 suggested `unreachable:` lines the fetcher's table lacked."""
    sec = FETCHER[FETCHER.index("## 4 · Stop-conditions"):]
    sec = sec[:sec.index("\n## ", 5)]
    rows = re.findall(r"^\| `(?P<r>[^`]+)` \| (?P<w>.+?) \|$", sec, re.M)
    assert [(r, w) for r, w in rows] == [(x.wording, x.when) for x in stops.REASONS]


def _all_suggested(r):
    out = list(r.get("stop_lines_to_add", []))
    out += [x["suggested_stop_line"] for x in r.get("needs_operator", []) if x.get("suggested_stop_line")]
    out += [f["next_step"][6:] for f in r.get("failures", []) if f["next_step"].startswith("stop: ")]
    return out


def test_every_line_capture_suggests_is_in_the_vocabulary(subject, seqweb, monkeypatch):
    (subject / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nDisallow: /private/\n")
    pages = {f"https://{HOST}/404": (404, b"", ""), f"https://{HOST}/403": (403, b"", ""),
             f"https://{HOST}/doc.pdf": (200, b"%PDF", "application/pdf"),
             f"https://{HOST}/flaky": (0, b"", ""),
             f"https://{HOST}/app": (200, b'<div id="root"></div><script src="a.js"></script>', "text/html")}
    seqweb(pages)
    urls = list(pages) + [f"https://{HOST}/private/x"]
    _, r = _cap(subject, "--surface", "docs", *sum((["--url", u] for u in urls), []))
    for _ in range(3):
        _cap(subject, "--surface", "docs", "--retry-failed")
    _, st = _cap(subject, "--surface", "docs", "--status")
    lines = _all_suggested(r) + [x["suggested_stop_line"] for x in st["needs_operator"] if x["suggested_stop_line"]]
    assert len(lines) >= 6
    for ln in lines:
        stops.parse_line(ln)


# ── #10 TLS failures are final ───────────────────────────────────────────────

class TLSWeb(SeqWeb):
    def __init__(self, pages, exc):
        super().__init__(pages)
        self.exc = exc

    def __call__(self, req, timeout=None):
        self.asked.append(req.full_url)
        raise urllib.error.URLError(self.exc)


def test_a_tls_protocol_failure_is_final_and_tried_once(subject, monkeypatch, seqweb):
    seqweb({})
    w = TLSWeb({}, ssl.SSLError(1, "[SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1 alert protocol version"))
    monkeypatch.setattr(fetch, "_open", w)
    a = f"https://{HOST}/tls"
    code, r = _cap(subject, "--surface", "docs", "--url", a)
    assert w.asked == [a], "the same interpreter fails the same way: one attempt"
    assert r["failures"][0]["class"] == "final" and r["failures"][0]["reason"].startswith("TLS:")
    op = r["needs_operator"][0]
    assert op["next_step"] == "operator" and "newer TLS" in op["options"][0]
    assert op["suggested_stop_line"].startswith(f"- {a} | unreachable: TLS:")


def test_a_connection_dropped_in_the_handshake_may_pass(subject, monkeypatch, seqweb):
    seqweb({})
    w = TLSWeb({}, ssl.SSLEOFError(8, "EOF occurred in violation of protocol"))
    monkeypatch.setattr(fetch, "_open", w)
    a = f"https://{HOST}/eof"
    code, r = _cap(subject, "--surface", "docs", "--url", a)
    assert len(w.asked) == 3 and r["failures"][0]["class"] == "transient"


# ── #2 the fallback tree: the site's own copy, then the operator ─────────────

def test_a_refused_page_is_captured_from_its_markdown_twin(subject, seqweb):
    a = f"https://{HOST}/hooks/retries"
    w = seqweb({a: (403, b"", ""), a + ".md": MD})
    code, r = _cap(subject, "--surface", "docs", "--url", a)
    assert code == 0 and w.asked == [a, a + ".md"]
    p = r["pages"][0]
    assert p["fetch_method"] == "site-copy" and p["url"] == a and p["served_by"] == a + ".md"
    text = (subject / f"_capture-{r['batch']}.raw.txt").read_text()
    assert text.startswith(f"=====BEGIN {a}=====\n# Retries\n"), "keyed by the page it is a copy of"
    assert r["failures"] == [] and r["needs_operator"] == []


def test_a_copy_that_is_html_or_off_robots_is_not_used(subject, seqweb):
    a, b = f"https://{HOST}/x", f"https://{HOST}/y"
    (subject / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nDisallow: /y.md\n")
    w = seqweb({a: (403, b"", ""), a + ".md": (200, b"<!doctype html><p>a page</p>" * 10, "text/plain"),
                b: (403, b"", ""), b + ".md": MD})
    code, r = _cap(subject, "--surface", "docs", "--url", a, "--url", b)
    assert code == 1 and b + ".md" not in w.asked, "robots decides for the copy too"
    assert [f["tried"] for f in r["failures"]] == [["direct", f"site-copy {a}.md"], ["direct", f"site-copy {b}.md"]]
    op = r["needs_operator"]
    assert [x["suggested_stop_line"] for x in op] == [f"- {a} | refused: HTTP 403", f"- {b} | refused: HTTP 403"]
    assert op[0]["options"][0] == "the operator supplies the material"


def test_a_host_refusing_every_page_is_offered_one_line_that_closes_the_surface(subject, seqweb):
    den = _den(subject, n=4)
    seqweb({f"https://{HOST}/p{i}": (403, b"", "") for i in range(1, 5)})
    code, r = _cap(subject, "--surface", "help", "--denominator", str(den))
    closing = [x for x in r["needs_operator"] if x.get("scope") == "surface"]
    assert len(closing) == 1 and closing[0]["pages_refused"] == 4
    assert closing[0]["suggested_stop_line"] == f"- https://{HOST}/p1 | refused: HTTP 403 (surface help)"


def test_a_javascript_shell_is_read_from_its_copy_before_it_is_stopped(subject, seqweb):
    a = f"https://{HOST}/app"
    shell = (200, b'<html><body><div id="root"></div><script src="/a.js"></script></body></html>', "text/html")
    seqweb({a: shell, a + ".md": MD})
    code, r = _cap(subject, "--surface", "docs", "--url", a)
    assert code == 0 and r["pages"][0]["fetch_method"] == "site-copy" and r["stop_lines_to_add"] == []


def test_every_failure_carries_a_next_step_from_code(subject, seqweb):
    seqweb({f"https://{HOST}/gone": (404, b"", ""), f"https://{HOST}/flaky": (0, b"", ""),
            f"https://{HOST}/out": (200, PAGE.encode(), "text/html")})
    _, r = _cap(subject, "--surface", "docs", "--url", f"https://{HOST}/gone", "--url", f"https://{HOST}/flaky")
    assert {f["url"].rsplit("/", 1)[1]: f["next_step"] for f in r["failures"]} == {"gone": "operator", "flaky": "retry"}


# ── #1 a same-day correction supersedes; #5 a selection by path ─────────────

LLMS = b"""# Example
## Guides
- [Start](https://docs.example.test/en/start)
- [Hooks](https://docs.example.test/ja/hooks)
## Compare
- [Versus](https://docs.example.test/en/versus)
"""


def _llms(seqweb, body=LLMS):
    return seqweb({f"https://{HOST}/llms.txt": (200, body, "text/plain"),
                   **{f"https://{HOST}/{p}": OK for p in ("en/start", "ja/hooks", "en/versus")}})


def test_supersede_writes_a_lettered_file_and_keeps_the_first(subject, seqweb):
    _llms(seqweb)
    args = ("--surface", "docs", "--rung", "1", "--url", f"https://{HOST}/llms.txt")
    assert run_index(subject, *args)[0] == 0
    code, r = run_index(subject, *args)
    assert code == 1 and "--supersede" in r["refused"]
    code, r = run_index(subject, *args, "--path-prefix", "/en/", "--supersede")
    assert code == 0 and r["supersedes"] == f"_denominator-docs-{DAY}.md"
    b = subject / f"_denominator-docs-{DAY}b.md"
    assert b.read_text().splitlines()[0].endswith(f"· supersedes _denominator-docs-{DAY}.md")
    assert (subject / f"_denominator-docs-{DAY}.md").exists(), "never pruned, never overwritten"
    code, r = run_index(subject, *args, "--supersede")
    assert code == 0 and r["denominator"].endswith(f"{DAY}c.md")
    assert capture.current_denominator(subject, "docs").name == f"_denominator-docs-{DAY}c.md"


def test_supersede_needs_a_denominator_of_today(subject, seqweb):
    _llms(seqweb)
    code, r = run_index(subject, "--surface", "docs", "--rung", "1", "--url", f"https://{HOST}/llms.txt",
                        "--supersede")
    assert code == 1 and "to supersede" in r["refused"]


def test_resume_follows_the_current_denominator_only(subject, seqweb):
    old = _den(subject, n=3)
    seqweb({f"https://{HOST}/p{i}": ok_page(i) for i in range(1, 4)})
    _cap(subject, "--surface", "docs", "--denominator", str(old), "--max-pages", "1")
    new = subject / f"_denominator-docs-{DAY}b.md"
    new.write_text(old.read_text() + "")
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(old), "--resume")
    assert code == 1 and "superseded by" in r["refused"]
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(new), "--resume")
    assert code == 1 and "no window cut from" in r["refused"], "the old chain is kept, not followed"
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(new), "--max-pages", "1")
    assert code == 0 and r["offset"] == 0 and r["denominator"] == new.name
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(new), "--resume")
    assert code == 0 and r["offset"] == 1
    _, st = _cap(subject, "--surface", "docs", "--status")
    assert st["current_denominator"] == new.name and st["resume_from"] == 3


def test_select_prefix_takes_the_items_under_a_path_and_is_kept_on_resume(subject, seqweb):
    den = subject / f"_denominator-help-{DAY}.md"
    den.write_text("Index: help, rung 3 — x\n" + "".join(
        f"https://{HOST}/hc/{lang}/a{i}\n" for i in range(3) for lang in ("en-us", "ja")))
    w = seqweb({f"https://{HOST}/hc/{l}/a{i}": ok_page(f"{l}{i}") for i in range(3) for l in ("en-us", "ja")})
    code, r = _cap(subject, "--surface", "help", "--denominator", str(den), "--select-prefix", "/hc/en-us/",
                   "--max-pages", "2")
    assert code == 0 and r["selected_items"] == 3 and r["select_prefix"] == ["/hc/en-us/"]
    code, r = _cap(subject, "--surface", "help", "--denominator", str(den), "--resume")
    assert r["window_end"] == "exhausted" and [p["url"] for p in r["pages"]] == [f"https://{HOST}/hc/en-us/a2"]
    assert not any("/ja/" in u for u in w.asked)
    assert den.read_text().count("/ja/") == 3, "the denominator stays complete"


def test_select_prefix_drift_and_mixing_are_refused(subject, seqweb):
    den = _den(subject, n=3)
    seqweb({f"https://{HOST}/p{i}": ok_page(i) for i in range(1, 4)})
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(den), "--select", "2", "--select-prefix", "/p")
    assert code == 1 and "not both" in r["refused"]
    _cap(subject, "--surface", "docs", "--denominator", str(den), "--select-prefix", "/p", "--max-pages", "1")
    code, r = _cap(subject, "--surface", "docs", "--denominator", str(den), "--resume", "--select-prefix", "/p1")
    assert code == 1 and "scope would drift" in r["refused"]


# ── #4 an inventory that reads nothing it should not ────────────────────────

def test_status_files_lists_the_surfaces_files_with_sizes(subject, seqweb):
    den = _den(subject, n=1)
    w = seqweb({f"https://{HOST}/p1": OK})
    _, r = _cap(subject, "--surface", "docs", "--denominator", str(den))
    (subject / f"_collect-{r['batch']}-staging.md").write_text("x")
    (subject / f"_map-{r['batch']}-A.jsonl").write_text("{}\n")
    (subject / "_capture-help-2026-10-18-w01.raw.txt").write_text("other surface")
    asked = len(w.asked)
    code, st = _cap(subject, "--surface", "docs", "--status", "--files")
    assert code == 0 and len(w.asked) == asked
    f = st["files"]
    assert [x["name"] for x in f["captures"]] == [f"_capture-{r['batch']}.raw.txt"]
    assert f["staging"] == [{"name": f"_collect-{r['batch']}-staging.md", "bytes": 1}]
    assert [x["name"] for x in f["maps"]] == [f"_map-{r['batch']}-A.jsonl"]
    assert [x["name"] for x in f["denominators"]] == [den.name]
    assert f["receipts"][0]["name"] == f"_raw/{r['batch']}/RECEIPT.json"
    code, r = _cap(subject, "--surface", "docs", "--files")
    assert code == 1 and "--status" in r["refused"]


# ── #12 sections from the index's own headings; #24 the plan's probe ────────

def test_an_llms_txt_is_sectioned_by_its_own_headings(subject, seqweb):
    _llms(seqweb)
    code, r = run_index(subject, "--surface", "docs", "--rung", "1", "--url", f"https://{HOST}/llms.txt")
    assert code == 0 and r["sections_by"] == "## headings"
    assert r["sections"] == [{"section": "Guides", "items": 2, "lines": "2-3"},
                             {"section": "Compare", "items": 1, "lines": "4"}]


def test_heading_sections_count_only_the_items_a_path_prefix_kept(subject, seqweb):
    _llms(seqweb)
    code, r = run_index(subject, "--surface", "docs", "--rung", "1", "--url", f"https://{HOST}/llms.txt",
                        "--path-prefix", "/en/")
    assert r["sections"] == [{"section": "Guides", "items": 1, "lines": "2"},
                             {"section": "Compare", "items": 1, "lines": "3"}]
    lines = (subject / f"_denominator-docs-{DAY}.md").read_text().splitlines()
    assert lines[1].endswith("(https://docs.example.test/en/start)") and "versus" in lines[2]


def test_the_plan_flags_a_host_that_refuses_our_fetcher(subject, seqweb):
    h = "help.example.test"
    (subject / f"_robots-{h}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    body = (f"# Help\n- [A](https://{h}/a)\n- [B](https://{h}/b)\n- [C](https://third.test/c)\n").encode()
    w = seqweb({f"https://{h}/llms.txt": (200, body, "text/plain"), f"https://{h}/a": (403, b"", ""),
                f"https://{h}/a.md": (404, b"", "")})
    code, r = run_index(subject, "--surface", "help", "--rung", "1", "--url", f"https://{h}/llms.txt")
    assert code == 0
    by_host = {p["host"]: p for p in r["probe"]}
    assert by_host[h]["flag"] == "refused: HTTP 403" and by_host[h]["site_copy_status"] == 404
    assert by_host["third.test"]["probed"] is False, "a host G0 never ran for is not touched"
    assert not any("third.test" in u for u in w.asked)
    assert f"https://{h}/b" not in w.asked, "one page per host"


def test_an_index_the_host_refuses_offers_a_stop_line_for_the_surface(subject, seqweb):
    seqweb({f"https://{HOST}/sitemap.xml": (403, b"", "")})
    code, r = run_index(subject, "--surface", "help", "--rung", "3", "--url", f"https://{HOST}/sitemap.xml")
    assert code == 1 and r["next_step"] == "operator"
    assert r["suggested_stop_line"] == f"- https://{HOST}/sitemap.xml | refused: HTTP 403 (surface help)"
    stops.parse_line(r["suggested_stop_line"])


# ── a closing line closes the surface's items on its own host ────────────────

def _stg(d, batch, url):
    p = d / f"_collect-{batch}-staging.md"
    p.write_text(f"---\nbatch: {batch}\n---\n```json\n" + json.dumps(
        {"id": "x.help.a", "source_url": url, "vendor_term": "A"}) + "\n```\n")
    return p


def test_g4_counts_items_closed_by_a_surface_line_apart_from_evidence(tmp_path):
    den = tmp_path / f"_denominator-help-{DAY}.md"
    den.write_text("Index: help\nhttps://help.x.test/a\nhttps://help.x.test/b\nhttps://help.x.test/c\n"
                   "https://other.x.test/d\n")
    rows = _stg(tmp_path, f"help-{DAY}-w01", "https://help.x.test/a")
    st = tmp_path / "_stop-conditions.md"
    st.write_text("- https://help.x.test/b | refused: HTTP 403 (surface help)\n")
    v, code = g4_completeness.run(["--denominator", str(den), "--rows", str(rows), "--stops", str(st)])
    assert code == 1, "the other host's item is still open"
    assert v.counts["existence_closed_by_surface_line"] == 1  # c; b is keyed by its own line
    assert v.counts["existence_stopped"] == 1 and v.counts["evidence_covered_by_url"] == 1
    assert [f.where for f in v.findings] == ["https://other.x.test/d"]


def test_g4_ignores_a_closing_line_for_another_surface_or_outside_the_vocabulary(tmp_path):
    den = tmp_path / f"_denominator-help-{DAY}.md"
    den.write_text("Index: help\nhttps://help.x.test/a\nhttps://help.x.test/c\n")
    rows = _stg(tmp_path, f"help-{DAY}-w01", "https://help.x.test/a")
    st = tmp_path / "_stop-conditions.md"
    for line in ("- https://help.x.test/b | refused: HTTP 403 (surface docs)",
                 "- https://help.x.test/b | blocked somehow (surface help)"):
        st.write_text(line + "\n")
        v, code = g4_completeness.run(["--denominator", str(den), "--rows", str(rows), "--stops", str(st)])
        assert code == 1 and v.counts["existence_closed_by_surface_line"] == 0


def test_a_denominator_beside_a_closing_line_is_a_closed_surface_not_a_contradiction(tmp_path):
    d = tmp_path
    for s in ("product", "docs", "help"):
        (d / f"_denominator-{s}-{DAY}b.md").write_text("Index: x\nhttps://x.test/a\n")
        _stg(d, f"{s}-{DAY}-w01", "https://x.test/a")
    (d / "_stop-conditions.md").write_text("- https://x.test/a | refused: HTTP 403 (surface help)\n")
    v, code = surfaces.run(["--subject", str(d)])
    assert code == 0, [f.code for f in v.findings]
    assert v.counts["surfaces"]["help"]["state"] == "denominator, closed by a stop line"
    assert v.counts["surfaces"]["docs"]["denominators"] == [f"_denominator-docs-{DAY}b.md"]
    (d / "_stop-conditions.md").write_text("- https://help.x.test/ | surface help not published: none\n")
    v, code = surfaces.run(["--subject", str(d)])
    assert code == 1 and "surface_contradiction" in {f.code for f in v.findings}


# ── #9 the story's role is the line's role ───────────────────────────────────

FX = ROOT / "tests" / "fixtures" / "contract"
B = "docs-2026-01-31"


def _map(tmp_path, edit):
    src = FX / "K5" / "pass"
    lines = (src / f"_map-{B}-A.jsonl").read_text().splitlines()
    objs = [json.loads(ln) for ln in lines]
    edit(objs)
    m = tmp_path / f"_map-{B}-A.jsonl"
    m.write_text("".join(json.dumps(o) + "\n" for o in objs))
    return mapcheck.run(["--staging", str(src / f"_collect-{B}-staging.md"), "--map", str(m),
                         "--codebook", str(FX / "ref" / "codebook.md"),
                         "--elements", str(FX / "ref" / "elements.jsonl")])


def test_a_story_whose_role_is_not_the_role_fails(tmp_path):
    def edit(objs):
        objs[0]["user_story"] = "As a company admin, I want inbox so that work"
        objs[1]["user_story"] = "Reports for admins"
    v, code = _map(tmp_path, edit)
    assert code == 1
    msgs = [f.message for f in v.findings if f.code == "story_role_mismatch"]
    assert len(msgs) == 2 and "company admin" in msgs[0] and "does not open" in msgs[1]


def test_case_and_punctuation_do_not_make_a_mismatch(tmp_path):
    def edit(objs):
        objs[0]["user_story"] = "As an Admin, I want the shared inbox"
    v, code = _map(tmp_path, edit)
    assert "story_role_mismatch" not in {f.code for f in v.findings}


def test_story_words_from_neither_row_nor_element_are_listed_not_failed(tmp_path):
    def edit(objs):
        objs[0]["user_story"] = ("As an admin, I want the shared inbox to reply to every customer message "
                                 "so that calls reach the right agent")
    v, code = _map(tmp_path, edit)
    out = v.counts["per_mapper"]["A"]["story_words_outside_row_and_element"]
    first = next(x for x in out if x["id"] == "example.docs.inbox")
    assert first["words"] == ["calls", "reach", "right", "agent"]
    assert "story_role_mismatch" not in {f.code for f in v.findings}


# ── #8 the check is the counter ──────────────────────────────────────────────

def test_the_check_prints_rows_and_distinct_terms_per_batch(fx, capsys):
    from kbqa import report
    d = fx("good")
    stg = next(d.glob("_collect-*-staging.md"))
    batch = stg.name[len("_collect-"):-len("-staging.md")]
    report.run(["--vendor-dir", str(d), "--batch", batch])
    out = capsys.readouterr().out
    from kbqa.parsing import parse_staging
    rows = [r.obj for r in parse_staging(stg).rows if r.obj is not None]
    want = f"rows={len(rows)}  distinct_vendor_terms={len({r['vendor_term'] for r in rows})}"
    assert want in out and len(rows) > 0


def test_the_mapping_line_carries_each_passes_totals():
    import subprocess
    import sys
    v, _ = mapcheck.run(["--staging", str(FX / "K5" / "pass" / f"_collect-{B}-staging.md"),
                         "--map", str(FX / "K5" / "pass" / f"_map-{B}-A.jsonl"),
                         "--map", str(FX / "K5" / "pass" / f"_map-{B}-B.jsonl"),
                         "--codebook", str(FX / "ref" / "codebook.md"),
                         "--elements", str(FX / "ref" / "elements.jsonl")])
    out = subprocess.run([sys.executable, str(ROOT / "skills" / "kbqa-check" / "scripts" / "summ.py")],
                         input=v.to_json(), capture_output=True, text=True).stdout
    assert "A: mapped 3, needs-human 1" in out and "B: mapped" in out


# ── the pre-PR review of v6.18.0 ────────────────────────────────────────────

def test_r1_an_index_level_line_never_closes_another_rungs_items(tmp_path):
    """R1, reproduced: rung 1 (llms.txt) was excluded by robots, rung 2 (a
    sitemap) listed three help pages, no row was written. v6.17.1 failed this;
    the first v6.18.0 build passed it with all three items 'closed'."""
    den = tmp_path / f"_denominator-help-{DAY}.md"
    den.write_text("Index: help, rung 2 — https://help.x.test/sitemap.xml\n"
                   "https://help.x.test/a\nhttps://help.x.test/b\nhttps://help.x.test/c\n")
    rows = tmp_path / f"_collect-help-{DAY}-w01-staging.md"
    rows.write_text(f"---\nbatch: help-{DAY}-w01\n---\n```json\n```\n")
    st = tmp_path / "_stop-conditions.md"
    st.write_text("- https://help.x.test/llms.txt | excluded: robots /llms.txt (surface help)\n")
    v, code = g4_completeness.run(["--denominator", str(den), "--rows", str(rows), "--stops", str(st)])
    assert code == 1 and v.counts["without_row"] == 3
    assert v.counts["existence_closed_by_surface_line"] == 0


@pytest.mark.parametrize("reason", ["unreachable: HTTP 404", "js-only: not readable", "gated: login",
                                    "excluded: robots /b", "third-party host: other.test"])
def test_r1_a_one_page_reason_closes_one_page_even_with_a_surface_suffix(tmp_path, reason):
    den = tmp_path / f"_denominator-help-{DAY}.md"
    den.write_text("Index: help\nhttps://help.x.test/a\nhttps://help.x.test/b\nhttps://help.x.test/c\n")
    rows = _stg(tmp_path, f"help-{DAY}-w01", "https://help.x.test/a")
    st = tmp_path / "_stop-conditions.md"
    st.write_text(f"- https://help.x.test/b | {reason} (surface help)\n")
    v, code = g4_completeness.run(["--denominator", str(den), "--rows", str(rows), "--stops", str(st)])
    assert code == 1 and [f.where for f in v.findings] == ["https://help.x.test/c"]
    assert v.counts["existence_closed_by_surface_line"] == 0 and v.counts["existence_stopped"] == 1


def test_r1_the_surfaces_check_accepts_only_the_line_g4_accepts(tmp_path):
    d = tmp_path
    for s in ("product", "docs", "help"):
        (d / f"_denominator-{s}-{DAY}.md").write_text("Index: x\nhttps://help.x.test/a\n")
        _stg(d, f"{s}-{DAY}-w01", "https://help.x.test/a")
    for line in ("- https://help.x.test/llms.txt | excluded: robots /llms.txt (surface help)",
                 "- https://help.x.test/a | unreachable: HTTP 404 (surface help)",
                 "- https://help.x.test/other | refused: HTTP 403 (surface help)"):
        (d / "_stop-conditions.md").write_text(line + "\n")
        v, code = surfaces.run(["--subject", str(d)])
        assert code == 1 and "surface_contradiction" in {f.code for f in v.findings}, line


def test_r2_an_unusual_host_never_crashes_a_window(subject, seqweb):
    """R2, reproduced: page A redirects to a host with an underscore; page B is
    fine. The first v6.18.0 build crashed before writing anything."""
    a, b = f"https://{HOST}/a", f"https://{HOST}/b"

    class Redirect(SeqWeb):
        def __call__(self, req, timeout=None):
            if req.full_url == a:
                self.asked.append(a)
                from test_capture import _Resp
                return _Resp("https://my_cdn.example.com/a", 200, PAGE.encode(), "text/html")
            return super().__call__(req, timeout)
    import kbqa.fetch as f_
    w = Redirect({b: OK})
    seqweb({})
    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(f_, "_open", w)
    try:
        code, r = _cap(subject, "--surface", "docs", "--url", a, "--url", b)
    finally:
        mp.undo()
    assert code == 0 and [p["url"] for p in r["pages"]] == [b], "the healthy page is kept"
    assert r["stop_lines_to_add"] == [f"- {a} | third-party host: my_cdn.example.com"]
    assert (subject / "_raw" / r["batch"] / "WINDOW.json").exists()


def test_r2_a_stop_line_the_vocabulary_cannot_read_goes_to_the_operator(subject, seqweb, monkeypatch):
    """Whatever fetched data does to a line, the page is a failure handed to
    the operator and the window is recorded — never a crash."""
    a, b = f"https://{HOST}/a", f"https://{HOST}/b"
    seqweb({a: (200, PAGE.encode(), "text/html"), b: OK})
    monkeypatch.setattr(fetch.Robots, "check", lambda self, u: (False, "") if u == a else (True, None))
    code, r = _cap(subject, "--surface", "docs", "--url", a, "--url", b)
    assert code == 0 and [p["url"] for p in r["pages"]] == [b]
    assert r["excluded"][0]["next_step"] == "operator"
    assert r["needs_operator"][0]["url"] == a and r["needs_operator"][0]["next_step"] == "operator"


def test_r2_real_hosts_and_rules_read_as_reasons():
    for ln in ("- https://x.test/a | third-party host: my_cdn.example.com",
               "- https://x.test/a | third-party host: bücher.example",
               "- https://x.test/a | excluded: robots /a b/",
               "- https://x.test/a | excluded: robots /a b/ (surface help)"):
        stops.parse_line(ln)


def test_r1_a_refusal_keyed_by_an_index_url_closes_no_item(tmp_path):
    """Even a reason that may close items does so only when keyed by an item of
    this denominator: a refused rung-1 index says nothing of rung 2's pages."""
    den = tmp_path / f"_denominator-help-{DAY}.md"
    den.write_text("Index: help, rung 3\nhttps://help.x.test/a\nhttps://help.x.test/b\n")
    rows = _stg(tmp_path, f"help-{DAY}-w01", "https://help.x.test/a")
    st = tmp_path / "_stop-conditions.md"
    st.write_text("- https://help.x.test/llms.txt | refused: HTTP 403 (surface help)\n")
    v, code = g4_completeness.run(["--denominator", str(den), "--rows", str(rows), "--stops", str(st)])
    assert code == 1 and v.counts["existence_closed_by_surface_line"] == 0
