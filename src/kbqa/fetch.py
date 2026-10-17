"""Fetching for `kbqa capture` and `kbqa index`: one request path, robots in code.

Permission is decided here, from the robots.txt that `kbqa g0` recorded today —
never by an agent reading the file. No record dated today for a host means no
fetch from it: G0 runs per host per collection run, and this enforces it.

For each path the rules of three user-agent groups apply — `Claude-User` (a
fetch a person asked for), `ClaudeBot`, and `*` — each by its own group, else
`*` (RFC 9309 §2.2.1), and the stricter reading holds: a path any of them
disallows is not fetched. Matching is RFC 9309 §2.2.2: the longest matching
rule wins, `*` matches any run of characters, `$` anchors the end, and on a tie
`allow` wins. The longest crawl delay of the three is honoured between requests
to the same host.
"""

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from . import __version__
from .gates.g0_permission import OUR_AGENTS, _applicable_group, _delay_seconds, _parse_groups

USER_AGENT = f"Mozilla/5.0 (compatible; kbqa-capture/{__version__}; +https://github.com/ramygwprod/kb-qa)"
TIMEOUT = 30
MAX_BYTES = 20 * 1024 * 1024
THROTTLE_STATUSES = (429, 503)
# A failure that may pass gets this many attempts in one run, with these waits
# between them; nothing is ever retried without limit.
ATTEMPTS = 3
BACKOFF = (2.0, 5.0)
TRANSIENT_STATUSES = (408, 500, 502, 504)

# Patched by tests; the network is never reached from the test suite.
_open = urllib.request.urlopen
_sleep = time.sleep


class FetchError(Exception):
    """A request that failed in transport — it may pass on another attempt."""


class TooLarge(FetchError):
    """A response over the size limit — another attempt cannot help."""


@dataclass
class Response:
    requested: str
    url: str          # the URL that served the bytes, after redirects
    status: int
    content_type: str
    body: bytes


def get(url: str, max_bytes: int = MAX_BYTES) -> Response:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _open(req, timeout=TIMEOUT) as resp:
            body = resp.read(max_bytes + 1)
            served = resp.geturl()
            status = resp.status
            ctype = resp.headers.get("Content-Type", "") or ""
    except urllib.error.HTTPError as exc:
        return Response(url, url, exc.code, "", b"")
    except Exception as exc:  # noqa: BLE001 — any transport failure is a failed fetch
        raise FetchError(f"{type(exc).__name__}: {exc}") from exc
    if len(body) > max_bytes:
        raise TooLarge(f"larger than {max_bytes} bytes")
    return Response(url, served, status, ctype, body)


def classify(status: int) -> str:
    if status == 200:
        return "ok"
    if status in THROTTLE_STATUSES:
        return "throttled"
    if status in TRANSIENT_STATUSES:
        return "transient"
    return "final"


def get_patiently(url: str, max_bytes: int = MAX_BYTES) -> Tuple[Optional[Response], str, int, str]:
    """(response, class, attempts, reason) — at most ATTEMPTS tries, and only a
    failure that may pass is tried again. Throttling is never retried here: it
    ends the window, and the next run resumes at that page."""
    reason = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = get(url, max_bytes)
        except TooLarge as exc:
            return None, "final", attempt, str(exc)
        except FetchError as exc:
            reason = str(exc)
        else:
            cls = classify(r.status)
            if cls == "ok":
                return r, "ok", attempt, ""
            reason = f"HTTP {r.status}"
            if cls != "transient":
                return r, cls, attempt, reason
        if attempt < ATTEMPTS:
            _sleep(BACKOFF[attempt - 1])
    return None, "transient", ATTEMPTS, reason


# ── robots ────────────────────────────────────────────────────────────────

def _rule_regex(pattern: str) -> "re.Pattern[str]":
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(rx + ("$" if anchored else ""))


def _path_of(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def _decide(group: Dict[str, List[str]], path: str) -> Tuple[bool, Optional[str]]:
    """(allowed, the rule that decided it) for one group."""
    best: Optional[Tuple[int, bool, str]] = None
    for kind in ("allow", "disallow"):
        for rule in group[kind]:
            rule = rule.strip()
            if not rule:
                continue  # an empty Disallow allows everything
            if _rule_regex(rule).match(path):
                key = (len(rule), kind == "allow", rule)
                if best is None or key[:2] > best[:2]:
                    best = key
    if best is None:
        return True, None
    return best[1], best[2]


@dataclass
class Robots:
    host: str
    record: Path
    groups: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)

    def applicable(self):
        return {a: _applicable_group(a, self.groups) for a in OUR_AGENTS}

    def check(self, url: str) -> Tuple[bool, Optional[str]]:
        """(allowed, disallow rule) — the stricter reading of our agents' groups."""
        path = _path_of(url)
        for _, (_, group) in self.applicable().items():
            ok, rule = _decide(group, path)
            if not ok:
                return False, rule
        return True, None

    def site_wide_refused(self) -> bool:
        return not self.check(f"https://{self.host}/")[0]

    def crawl_delay(self) -> float:
        delays = [_delay_seconds(d) for _, g in self.applicable().values() for d in g["crawl_delay"]]
        return max(delays) if delays else 0.0


def robots_for(subject: Path, host: str, day: str) -> Robots:
    """The robots record `kbqa g0` wrote for `host` today, parsed."""
    record = subject / f"_robots-{host}-{day}.txt"
    if not record.exists():
        raise FetchError(
            f"no robots record for {host} dated {day} ({record.name}). Permission comes first: "
            f"run `python3 -m kbqa g0 --host {host} --out <subject folder>`, then retry.")
    return Robots(host, record, _parse_groups(record.read_text(encoding="utf-8")))


class Pacer:
    """Honours each host's crawl delay between requests to that host."""

    def __init__(self) -> None:
        self.last: Dict[str, float] = {}

    def wait(self, host: str, delay: float) -> None:
        if delay > 0 and host in self.last:
            remaining = delay - (time.monotonic() - self.last[host])
            if remaining > 0:
                _sleep(remaining)
        self.last[host] = time.monotonic()


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def charset_of(content_type: str, body: bytes) -> str:
    m = re.search(r"charset=([\w.-]+)", content_type, re.I)
    if m:
        return m.group(1)
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w.-]+)", body[:4096], re.I)
    return m.group(1).decode("ascii", "replace") if m else "utf-8"


def decode(body: bytes, content_type: str) -> str:
    enc = charset_of(content_type, body)
    try:
        return body.decode(enc, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")
