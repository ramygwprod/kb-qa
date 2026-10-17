"""G0 · Permission — python -m kbqa g0 --host <host> --out <vendor-dir>

Fetch robots.txt, record it verbatim as Bronze, and decide whether our agent
may crawl at all.

⚠ Exit 2 is terminal for that vendor. No retry, no alternate fetcher.
"""

import argparse
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..verdict import DECLINED, ERROR, FAIL, PASS, Finding, Verdict, input_ref
from . import EXIT_DECLINED, EXIT_FAIL, EXIT_PASS

GATE = "g0_permission"

# The agents whose permission governs this project. Claude-User is the agent a
# site owner addresses for a fetch a person asked for — which every collection
# is (Anthropic, "Does Anthropic crawl data from the web…"). ClaudeBot is the
# training crawler, the only one G0 read before v6.16.0. Each is governed by its
# own group, else by `*` (RFC 9309 §2.2.1); the host is refused if either is.
OUR_AGENTS = ("claude-user", "claudebot")

_USER_AGENT = "ClaudeBot"
_TIMEOUT = 30


def _fetch(host: str) -> Tuple[Optional[str], Optional[str]]:
    url = f"https://{host}/robots.txt"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        # RFC 9309 §2.3.1.3: 4xx means no restrictions.
        if 400 <= exc.code < 500:
            return "", None
        return None, f"HTTP {exc.code} fetching {url}"
    except Exception as exc:  # noqa: BLE001 - any transport failure is "unreachable"
        return None, f"{type(exc).__name__} fetching {url}: {exc}"

    if status != 200:
        return None, f"HTTP {status} fetching {url}"
    return raw.decode("utf-8", errors="replace"), None


def _parse_groups(text: str) -> Dict[str, Dict[str, List[str]]]:
    """Parse robots.txt into {user-agent: {allow: [], disallow: [], crawl_delay: []}}.

    Per RFC 9309: consecutive user-agent lines share the following rule block.
    """
    groups: Dict[str, Dict[str, List[str]]] = {}
    current_agents: List[str] = []
    starting_new_group = True

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = line.split(":", 1)
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if not starting_new_group:
                current_agents = []
                starting_new_group = True
            agent = value.lower()
            current_agents.append(agent)
            groups.setdefault(agent, {"allow": [], "disallow": [], "crawl_delay": []})
            continue

        if field in ("allow", "disallow", "crawl-delay"):
            if not current_agents:
                continue
            starting_new_group = False
            key = {"allow": "allow", "disallow": "disallow", "crawl-delay": "crawl_delay"}[field]
            for agent in current_agents:
                groups[agent][key].append(value)

    return groups


def _applicable_group(agent: str, groups: Dict[str, Dict[str, List[str]]]) -> Tuple[Optional[str], Dict[str, List[str]]]:
    """RFC 9309 §2.2.1: the agent's own group if one names it, else `*`."""
    for name in (agent, "*"):
        if name in groups:
            return name, groups[name]
    return None, {"allow": [], "disallow": [], "crawl_delay": []}


def _delay_seconds(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _is_site_wide_disallow(group: Dict[str, List[str]]) -> bool:
    """Site-wide denial: `Disallow: /` with no Allow rule re-opening the root.

    An empty `Disallow:` means allow-all and must never be read as a denial.
    """
    disallows = [d for d in group["disallow"] if d.strip() != ""]
    if "/" not in disallows:
        return False
    # An `Allow: /` (or longer) rule at the root overrides per longest-match.
    return not any(a.strip() == "/" for a in group["allow"])


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int, Optional[Path]]:
    ap = argparse.ArgumentParser(prog="kbqa g0")
    ap.add_argument("--host", required=True)
    ap.add_argument("--out", required=True, help="vendor directory")
    ap.add_argument("--date", default=None, help="override capture date (tests)")
    args = ap.parse_args(argv)

    host = args.host.strip().lower()
    out_dir = Path(args.out)
    stamp = args.date or date.today().isoformat()
    artifact = out_dir / f"_robots-{host}-{stamp}.txt"

    text, err = _fetch(host)
    if text is None:
        v = Verdict(
            gate=GATE,
            verdict=ERROR,
            inputs={"host": {"host": host}},
            counts={},
            findings=[Finding("robots_unreachable", err or "unreachable")],
        )
        return v, EXIT_FAIL, None

    out_dir.mkdir(parents=True, exist_ok=True)
    artifact.write_text(text, encoding="utf-8")

    groups = _parse_groups(text)
    applied = {a: _applicable_group(a, groups) for a in OUR_AGENTS}
    refused = [a for a, (_, g) in applied.items() if _is_site_wide_disallow(g)]
    declined = bool(refused)

    findings: List[Finding] = []
    for a in refused:
        matched = applied[a][0]
        findings.append(
            Finding(
                "site_wide_disallow",
                f"user-agent {a!r} (group {matched!r}) is disallowed site-wide; vendor is closed",
            )
        )
    # The stricter reading of the two: every rule that applies to either agent,
    # and the longest crawl delay.
    agent = applied[(refused or list(OUR_AGENTS))[0]][0]
    group = {k: sorted({v for _, g in applied.values() for v in g[k]})
             for k in ("allow", "disallow", "crawl_delay")}
    group["crawl_delay"].sort(key=_delay_seconds, reverse=True)

    v = Verdict(
        gate=GATE,
        verdict=DECLINED if declined else PASS,
        inputs={"robots": input_ref(artifact), "host": {"host": host}},
        counts={
            "disallow_rules": len(group["disallow"]),
            "allow_rules": len(group["allow"]),
        },
        findings=findings,
        extra={
            "matched_user_agent": agent,
            "crawl_delay": group["crawl_delay"][0] if group["crawl_delay"] else None,
            "disallow": list(group["disallow"]),
            "allow": list(group["allow"]),
        },
    )
    return v, (EXIT_DECLINED if declined else EXIT_PASS), artifact
