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

# The agents whose permission actually governs this project.
OUR_AGENTS = ("claudebot", "*")

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


def _applicable_group(groups: Dict[str, Dict[str, List[str]]]) -> Tuple[Optional[str], Dict[str, List[str]]]:
    """RFC 9309 §2.2.1: the most specific matching user-agent group wins."""
    for agent in OUR_AGENTS:
        if agent in groups:
            return agent, groups[agent]
    return None, {"allow": [], "disallow": [], "crawl_delay": []}


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
    agent, group = _applicable_group(groups)
    declined = _is_site_wide_disallow(group)

    findings: List[Finding] = []
    if declined:
        findings.append(
            Finding(
                "site_wide_disallow",
                f"user-agent {agent!r} is disallowed site-wide; vendor is closed",
            )
        )

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
