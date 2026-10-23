#!/usr/bin/env python3
"""Mutation check: every guard must be caught by its tests when it is broken.

    python scripts/mutate.py [--registry tests/mutations.json] [--root <repo>] [--only <label>]

A guard whose test passes with the guard removed is not guarded. Each entry of
the registry (`tests/mutations.json`) is one deliberate break:

    {"label": "...", "file": "src/kbqa/chrome.py",
     "old": "<exact text>", "new": "<the broken text>",
     "tests": ["tests/test_chrome_language_duplicates.py"]}

For each entry, one at a time: the file's `old` text — which must occur in it
exactly once — is replaced by `new`, in place; only the named tests run; then
the file's original bytes and timestamps are put back (always: try/finally),
and its sha256 is compared with what it was before. A mismatch stops the run at
once (exit 2), naming the file.

Before any mutation, each distinct set of tests is run on the unmutated tree: a
test that already fails would make every mutation look caught.

Prints one line per label — CAUGHT (with the test that failed), MISSED, NOT
FOUND (`old` absent, or present more than once), ERROR — and a final count.
Exits 0 only when every mutation is CAUGHT. "Caught" means the tests ran and
failed (pytest exit 1); a test file that cannot be collected, or a mutation
that does not even compile, is an ERROR, never a catch.

Bytecode is not written while mutations run (PYTHONDONTWRITEBYTECODE), so no
cache compiled from a mutated file can outlive the restore.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
KEYS = ("label", "file", "old", "new", "tests")


class RegistryError(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_registry(path: Path) -> List[dict]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read the registry {path}: {exc}")
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"{path} must hold a non-empty JSON list of mutations")
    seen = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or set(e) != set(KEYS):
            raise RegistryError(f"entry {i}: needs exactly the keys {', '.join(KEYS)}")
        if not all(isinstance(e[k], str) and e[k] for k in ("label", "file", "old")):
            raise RegistryError(f"entry {i}: label, file and old must be non-empty text")
        if not isinstance(e["new"], str) or e["new"] == e["old"]:
            raise RegistryError(f"entry {i} ({e['label']}): new must be text that differs from old")
        if not isinstance(e["tests"], list) or not e["tests"] or \
                not all(isinstance(t, str) and t for t in e["tests"]):
            raise RegistryError(f"entry {i} ({e['label']}): tests must be a non-empty list of test paths")
        if e["label"] in seen:
            raise RegistryError(f"entry {i}: the label {e['label']!r} is used twice")
        seen.add(e["label"])
    return entries


def _inside(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise RegistryError(f"{rel} is outside {root}")
    return p


def run_tests(root: Path, tests: List[str], python: str) -> Tuple[int, str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([python, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
                       cwd=str(root), env=env, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines() or [""]
    failed = next((ln.split(" - ")[0][len("FAILED "):] for ln in lines if ln.startswith("FAILED ")), None)
    # Which test caught it, so a catch for the wrong reason can be seen.
    return r.returncode, lines[-1] + (f"; by {failed}" if failed else "")


def mutate_one(root: Path, entry: dict, python: str) -> Tuple[str, str]:
    """(verdict, detail) for one entry. The file is always restored; a restore
    that does not reproduce the original sha256 raises SystemExit(2)."""
    path = _inside(root, entry["file"])
    if not path.is_file():
        return "NOT FOUND", f"no file {entry['file']}"
    original = path.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    stat = path.stat()
    text = original.decode("utf-8")
    n = text.count(entry["old"])
    if n != 1:
        return "NOT FOUND", f"`old` occurs {n} times in {entry['file']}, not exactly once"
    mutated = text.replace(entry["old"], entry["new"], 1)
    try:
        path.write_bytes(mutated.encode("utf-8"))
        code, tail = run_tests(root, entry["tests"], python)
    finally:
        path.write_bytes(original)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        after = sha256(path)
        if after != before:
            print(f"RESTORE FAILED  {entry['file']}: sha256 {after}, was {before}. Stop.", flush=True)
            raise SystemExit(2)
    if code == 1:
        return "CAUGHT", tail
    if code == 0:
        return "MISSED", tail
    return "ERROR", f"pytest exit {code}: {tail}"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Break each registered guard and check its tests catch it.")
    ap.add_argument("--root", default=str(ROOT), help="the repository (default: this script's)")
    ap.add_argument("--registry", default=None, help="default: <root>/tests/mutations.json")
    ap.add_argument("--only", action="append", default=[], help="run only this label (repeatable)")
    ap.add_argument("--python", default=sys.executable, help="the interpreter that runs pytest")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    registry = Path(args.registry) if args.registry else root / "tests" / "mutations.json"
    try:
        entries = load_registry(registry)
        for e in entries:
            _inside(root, e["file"])
    except RegistryError as exc:
        print(f"REFUSED: {exc}")
        return 1
    if args.only:
        unknown = sorted(set(args.only) - {e["label"] for e in entries})
        if unknown:
            print(f"REFUSED: no mutation labelled {', '.join(unknown)}")
            return 1
        entries = [e for e in entries if e["label"] in args.only]

    baseline: Dict[Tuple[str, ...], Tuple[int, str]] = {}
    for e in entries:
        key = tuple(e["tests"])
        if key not in baseline:
            baseline[key] = run_tests(root, list(key), args.python)
    broken = {k: v for k, v in baseline.items() if v[0] != 0}
    for k, (code, tail) in broken.items():
        print(f"BASELINE FAILS  {' '.join(k)}: pytest exit {code}: {tail}")
    if broken:
        print("No mutation was applied: the named tests must pass on the unmutated tree first.")
        return 1

    counts: Dict[str, int] = {}
    width = max(len(v) for v in ("CAUGHT", "MISSED", "NOT FOUND", "ERROR"))
    for e in entries:
        verdict, detail = mutate_one(root, e, args.python)
        counts[verdict] = counts.get(verdict, 0) + 1
        print(f"{verdict:<{width}}  {e['label']}  ({e['file']}; {detail})", flush=True)
    summary = ", ".join(f"{counts.get(v, 0)} {v.lower()}" for v in ("CAUGHT", "MISSED", "NOT FOUND", "ERROR"))
    print(f"mutations: {len(entries)} — {summary}")
    return 0 if counts.get("CAUGHT", 0) == len(entries) else 1


if __name__ == "__main__":
    sys.exit(main())
