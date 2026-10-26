"""kbqa collect-surface — the capture loop as one command, against a simulated web.

The fetcher used to run `kbqa capture` window by window by hand: the first
window, then `--resume` until the receipt said `exhausted`. Now code runs the
loop and says why it stopped; these tests hold it to capture's own rules.
"""

import contextlib
import io
import json

import pytest

from kbqa import cli, collect_surface, fetch, stops
from test_capture import DAY, HOST, SeqWeb, _cap, _den, ok_page


@pytest.fixture
def subject(tmp_path):
    d = tmp_path / "Example-Co"
    d.mkdir()
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    return d


@pytest.fixture
def seqweb(monkeypatch):
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)

    def install(pages):
        w = SeqWeb(pages)
        monkeypatch.setattr(fetch, "_open", w)
        return w
    return install


def _collect(subject, den, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = collect_surface.run(["--out", str(subject), "--surface", "docs", "--denominator", str(den),
                                    "--date", DAY, *args])
    return code, json.loads(out.getvalue())


def _url(i):
    return f"https://{HOST}/p{i}"


def _batch(n):
    return f"docs-{DAY}-w{n:02d}"


def test_it_runs_windows_until_the_selection_is_exhausted(subject, seqweb):
    den = _den(subject, n=5)
    seqweb({_url(i): ok_page(i) for i in range(1, 6)})
    code, r = _collect(subject, den, "--max-pages", "2")
    assert code == 0, r
    assert r["end"] == "exhausted" and "exhausted" in r["next_step"]
    assert [(w["batch"], w["window_end"], w["pages_captured"]) for w in r["windows"]] == [
        (_batch(1), "budget", 2), (_batch(2), "budget", 2), (_batch(3), "exhausted", 1)]
    assert r["retried_failed"] is False and r["needs_operator"] == [] and "refusal" not in r
    for w in r["windows"]:
        assert (subject / w["receipt"]).is_file() and w["capture"].endswith(f"_capture-{w['batch']}.raw.txt")


def test_it_writes_exactly_what_capture_run_by_hand_writes(tmp_path, seqweb):
    """Nothing of its own: the same files, byte for byte, as the windows run one by one."""
    def tree(d):
        # a receipt names its capture by path, so the folder's own name is set aside
        return {p.relative_to(d).as_posix(): p.read_bytes().replace(str(d).encode(), b"<subject>")
                for p in sorted(d.rglob("*")) if p.is_file()}
    dirs = []
    for name in ("loop", "by-hand"):
        d = tmp_path / name
        d.mkdir()
        (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
        dirs.append((d, _den(d, n=5)))
    seqweb({_url(i): ok_page(i) for i in range(1, 6)})
    (loop, den_a), (hand, den_b) = dirs
    assert _collect(loop, den_a, "--max-pages", "2")[0] == 0
    _cap(hand, "--surface", "docs", "--denominator", str(den_b), "--max-pages", "2")
    for _ in range(2):
        _cap(hand, "--surface", "docs", "--denominator", str(den_b), "--max-pages", "2", "--resume")
    assert tree(loop) == tree(hand)


def test_throttling_stops_the_run_and_the_next_run_resumes_at_that_page(subject, seqweb):
    den = _den(subject, n=4)
    seqweb({_url(1): ok_page(1), _url(2): [(429, b"", "text/html"), ok_page(2)],
            _url(3): ok_page(3), _url(4): ok_page(4)})
    code, r = _collect(subject, den)
    assert code == 0 and r["end"] == "throttled" and "later" in r["next_step"]
    assert [(w["batch"], w["stopped"], w["pages_captured"]) for w in r["windows"]] == [(_batch(1), "throttled", 1)]
    assert r["retried_failed"] is False, "failed pages wait for the end of the selection"
    code, r = _collect(subject, den)
    assert code == 0 and r["end"] == "exhausted"
    assert [w["batch"] for w in r["windows"]] == [_batch(2)]
    w2 = json.loads((subject / r["windows"][0]["receipt"]).read_text())
    assert [p["url"] for p in w2["pages"]] == [_url(2), _url(3), _url(4)]


def test_it_stops_after_max_windows_and_the_next_run_continues(subject, seqweb):
    den = _den(subject, n=5)
    seqweb({_url(i): ok_page(i) for i in range(1, 6)})
    code, r = _collect(subject, den, "--max-pages", "1", "--max-windows", "2")
    assert code == 0 and r["end"] == "window_limit" and "again" in r["next_step"]
    assert [w["batch"] for w in r["windows"]] == [_batch(1), _batch(2)]
    code, r = _collect(subject, den, "--max-pages", "1")
    assert r["end"] == "exhausted" and [w["batch"] for w in r["windows"]] == [_batch(3), _batch(4), _batch(5)]


def test_failed_pages_are_retried_once_per_run_after_exhaustion_within_captures_limit(subject, seqweb):
    den = _den(subject, n=2)
    w = seqweb({_url(1): ok_page(1), _url(2): (0, b"", "")})
    code, r = _collect(subject, den)
    assert code == 0 and r["end"] == "exhausted" and r["retried_failed"] is True
    assert [x["kind"] for x in r["windows"]] == ["window", "retry"], "one retry run, no more"
    code, r = _collect(subject, den)                         # the page's third run
    assert code == 0 and r["already_exhausted"] is True and [x["kind"] for x in r["windows"]] == ["retry"]
    asked = len(w.asked)
    code, r = _collect(subject, den)                         # capture's limit: no fourth run
    assert code == 0 and r["windows"] == [] and r["retried_failed"] is False and len(w.asked) == asked
    assert [x["url"] for x in r["needs_operator"]] == [_url(2)]
    assert r["needs_operator"][0]["suggested_stop_line"].endswith("in 3 runs")


def test_a_retry_run_that_is_throttled_ends_the_run_throttled(subject, seqweb):
    den = _den(subject, n=2)
    seqweb({_url(1): ok_page(1), _url(2): [(0, b"", ""), (0, b"", ""), (0, b"", ""), (429, b"", "")]})
    code, r = _collect(subject, den)
    assert r["retried_failed"] is True and r["end"] == "throttled"


def test_an_exhausted_surface_is_not_asked_again(subject, seqweb):
    den = _den(subject, n=2)
    w = seqweb({_url(1): ok_page(1), _url(2): ok_page(2)})
    assert _collect(subject, den)[1]["end"] == "exhausted"
    asked = len(w.asked)
    code, r = _collect(subject, den)
    assert code == 0, "a surface already done is not a failure"
    assert r["end"] == "exhausted" and r["already_exhausted"] is True and r["windows"] == []
    assert "refusal" not in r and len(w.asked) == asked


def test_a_superseded_denominator_is_refused_even_when_its_windows_are_done(subject, seqweb):
    old = _den(subject, n=2)
    seqweb({_url(1): ok_page(1), _url(2): ok_page(2)})
    assert _collect(subject, old)[1]["end"] == "exhausted"
    (subject / f"_denominator-docs-{DAY}b.md").write_text(old.read_text())
    code, r = _collect(subject, old)
    assert code == 1 and r["end"] == "refused" and "superseded by" in r["refusal"]["refused"]


def test_a_refusal_is_reported_word_for_word_not_hidden(subject, seqweb):
    den = _den(subject, n=4)
    seqweb({_url(i): ok_page(i) for i in range(1, 5)})
    _cap(subject, "--surface", "docs", "--denominator", str(den), "--select", "2-3", "--max-pages", "1")
    code, r = _collect(subject, den, "--select", "2-4")
    assert code == 1 and r["end"] == "refused" and r["windows"] == []
    assert "scope would drift" in r["refusal"]["refused"] and r["refusal"]["next_step"] == "operator"
    assert "word for word" in r["next_step"]


def test_robots_unreachable_is_its_own_end(subject, seqweb, monkeypatch):
    from kbqa.gates import g0_permission
    monkeypatch.setattr(g0_permission, "_fetch", lambda host: (None, f"URLError fetching {host}"))
    (subject / f"_robots-{HOST}-{DAY}.txt").unlink()
    den = _den(subject, n=2)
    w = seqweb({_url(1): ok_page(1), _url(2): ok_page(2)})
    code, r = _collect(subject, den)
    assert code == 1 and r["end"] == "robots_unreachable" and r["windows"] == []
    assert r["refusal"]["robots_unreachable"] == HOST and "could not be read" in r["refusal"]["refused"]
    assert not any(u.startswith(_url("")) for u in w.asked)


def test_needs_operator_is_merged_once_per_url(subject, seqweb):
    """A 404 is in its window's receipt, again in the retry run's, and again
    among the pages given up on: the operator sees it once."""
    den = _den(subject, n=3)
    seqweb({_url(1): ok_page(1), _url(2): (404, b"", ""), _url(3): (0, b"", "")})
    code, r = _collect(subject, den)
    assert r["retried_failed"] is True
    retry = json.loads((subject / r["windows"][1]["receipt"]).read_text())
    assert _url(2) in [x["url"] for x in retry["needs_operator"]], "the case this test is about"
    assert [x["url"] for x in r["needs_operator"]] == [_url(2)]


def test_a_surface_wide_item_is_kept_once_per_host():
    into = [{"url": "https://a.test/1", "reason": "first"}]
    collect_surface.merge_operator(into, [
        {"url": "https://a.test/1", "reason": "again"},
        {"scope": "surface", "host": "a.test", "suggested_stop_line": "one"},
        {"scope": "surface", "host": "a.test", "suggested_stop_line": "two"},
        {"scope": "surface", "host": "b.test", "suggested_stop_line": "three"}])
    assert [x.get("reason") or x["suggested_stop_line"] for x in into] == ["first", "one", "three"]


def test_stop_lines_are_merged_once_each_in_order():
    into = ["- https://a.test/1 | js-only: not readable"]
    collect_surface.merge_lines(into, ["- https://a.test/2 | not approved: pdf",
                                       "- https://a.test/1 | js-only: not readable"])
    assert into == ["- https://a.test/1 | js-only: not readable", "- https://a.test/2 | not approved: pdf"]


def test_a_window_of_copies_does_not_stop_the_loop_early(subject, seqweb):
    den = _den(subject, n=6)
    seqweb({_url(1): ok_page(1), _url(2): ok_page(2), _url(3): ok_page(1), _url(4): ok_page(2),
            _url(5): ok_page(5), _url(6): ok_page(6)})
    code, r = _collect(subject, den, "--max-pages", "2")
    assert code == 0 and r["end"] == "exhausted"
    assert [(w["pages_captured"], w["duplicates"], w["capture"] is None) for w in r["windows"]] == [
        (2, 0, False), (0, 2, True), (2, 0, False)]
    assert [ln for ln in r["stop_lines_to_add"] if "same text as" in ln] == [
        f"- {_url(3)} | no feature: same text as {_url(1)}", f"- {_url(4)} | no feature: same text as {_url(2)}"]


def test_a_window_of_a_copy_and_a_failure_does_not_stop_the_loop_either(subject, seqweb):
    """capture exits 1 for it (nothing captured, a failure) — the loop reads
    the receipt's window_end, never the exit code."""
    den = _den(subject, n=6)
    seqweb({_url(1): ok_page(1), _url(2): ok_page(2), _url(3): ok_page(1), _url(4): (404, b"", ""),
            _url(5): ok_page(5), _url(6): ok_page(6)})
    code, r = _collect(subject, den, "--max-pages", "2")
    assert code == 0 and r["end"] == "exhausted" and len(r["windows"]) == 3
    middle = r["windows"][1]
    assert (middle["window_end"], middle["pages_captured"], middle["duplicates"], middle["failures"]) == \
        ("budget", 0, 1, 1)
    assert _cap(subject, "--surface", "docs", "--status")[1]["exhausted"] is True


def test_a_window_that_captured_nothing_stops_the_surface(subject, seqweb):
    den = _den(subject, n=4)
    w = seqweb({_url(1): (0, b"", ""), _url(2): (0, b"", ""), _url(3): ok_page(3), _url(4): ok_page(4)})
    code, r = _collect(subject, den, "--max-pages", "2")
    assert code == 1 and r["end"] == "error" and [x["window_end"] for x in r["windows"]] == ["error"]
    assert _url(3) not in w.asked, "a host that will not load is not worked through"
    code, r = _collect(subject, den, "--max-pages", "2")
    assert code == 0 and r["end"] == "exhausted" and r["windows"][0]["batch"] == _batch(2)


def test_max_windows_below_one_is_refused_through_the_cli(subject, capsys):
    den = _den(subject, n=1)
    code = cli.main(["collect-surface", "--out", str(subject), "--surface", "docs", "--denominator", str(den),
                     "--max-windows", "0"])
    assert code == 1 and "--max-windows" in json.loads(capsys.readouterr().out)["refused"]
    assert not (subject / "_raw").exists()


# ── unstaged windows are never lost (v6.22.0, review S1) ─────────────────────

def test_every_window_with_a_capture_and_no_staging_is_listed_from_every_run(subject, seqweb):
    den = _den(subject, n=5)
    seqweb({_url(i): ok_page(i) for i in range(1, 6)})
    code, r = _collect(subject, den, "--max-pages", "2")
    assert code == 0 and [(u["batch"], u["state"]) for u in r["unstaged"]] == [
        (_batch(n), collect_surface.NO_DRAFTS) for n in (1, 2, 3)]
    assert r["unstaged"][0]["capture"] == str(subject / f"_capture-{_batch(1)}.raw.txt")
    assert r["unstaged"][0]["receipt"] == f"_raw/{_batch(1)}/RECEIPT.json"
    (subject / f"_collect-{_batch(1)}-staging.md").write_text("staged\n")
    (subject / f"_draft-{_batch(2)}.jsonl").write_text(json.dumps({"page": _url(3), "no_row": "x"}) + "\n")
    rec = json.loads((subject / "_raw" / _batch(3) / "RECEIPT.json").read_text())
    (subject / f"_draft-{_batch(3)}.jsonl").write_text(
        "".join(json.dumps({"page": p["url"], "no_row": "an overview"}) + "\n" for p in rec["pages"]))
    code, r = _collect(subject, den)  # a later run: the surface is exhausted, nothing new is captured
    assert code == 0 and r["already_exhausted"] and r["windows"] == []
    # drafted no_row throughout, but kbqa stage has not run: its stop lines are not recorded yet
    assert [(u["batch"], u["state"]) for u in r["unstaged"]] == [
        (_batch(2), collect_surface.DRAFTED), (_batch(3), collect_surface.STAGE_NOT_RUN)]
    for p in rec["pages"]:
        stops.add(subject, f"- {p['url']} | no feature: an overview")
    code, r = _collect(subject, den)
    assert [(u["batch"], u["state"]) for u in r["unstaged"]] == [
        (_batch(2), collect_surface.DRAFTED), (_batch(3), collect_surface.ALL_NO_ROW)]


def test_a_window_with_no_capture_file_is_not_unstaged(subject, seqweb):
    den = _den(subject, n=1)
    seqweb({_url(1): (404, b"", "text/html")})
    code, r = _collect(subject, den)
    assert r["windows"] and r["windows"][0]["capture"] is None, r
    assert r["unstaged"] == []
