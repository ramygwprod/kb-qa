#!/usr/bin/env python3
"""Bump the release: every current-version line, the manifest pin, then prove it.

    python scripts/release.py <new version> [--check] [--names <file>]

What it does, in order:
1. refuses when the working tree has uncommitted changes (untracked files
   included) outside the files it edits, or when the new version is not above
   the current one (`__version__`);
2. rewrites the version in exactly the lines of VERSION_LINES below — install,
   pin, "Version", "This copy is", `__version__`, `version =` lines — and
   nowhere else. A history note ("since v…", "before kbqa …") is never one of
   them; every other line holding the current version is listed, unchanged, so
   nothing is left out silently. A registered line that holds another version,
   or a registered pattern that matches nothing, is refused: the registry and
   the files have drifted, and a person decides which is right;
3. recomputes the manifest with the package's own `manifest.py` and rewrites
   `EXPECTED_MANIFEST` in the pre-flight — the whole hex token, never a fixed
   count of it;
4. runs the test suite and the mutation registry (`scripts/mutate.py`);
5. prints the brand scan and the push commands, which the operator runs.

`--check` changes nothing: it prints what it would change and what it would
refuse, and exits 1 when the release would be refused.

Every file is written atomically (a temporary file, then a rename), and only
after every change has been computed: either all of them land or none.
"""

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
V = r"\d+\.\d+\.\d+"
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

# (file, a pattern that finds a current-version line in it). Within a line it
# finds, every occurrence of the current version is replaced; nothing else in
# the file is touched.
VERSION_LINES: List[Tuple[str, str]] = [
    ("pyproject.toml", rf'^version = "{V}"$'),
    ("src/kbqa/__init__.py", rf'^__version__ = "{V}"$'),
    ("skills/kbqa-check/scripts/preflight.sh", rf'^PINNED="\$\{{KBQA_PINNED:-v{V}\}}"$'),
    ("skills/kbqa-check/SKILL.md", rf"the version this copy pins \(`v{V}`\)"),
    ("skills/kbqa-collect/SKILL.md", rf"^\*\*This copy is kbqa-collect v{V}\*\*, installed with kb-qa v{V}\."),
    ("skills/install.sh", rf"^#   bash skills/install\.sh v{V}$"),
    ("skills/install.sh", rf'^TAG="\$\{{1:\?usage: bash skills/install\.sh <tag, e\.g\. v{V}>\}}"$'),
    ("skills/README.md", rf"^bash skills/install\.sh v{V}$"),
    ("ci/estate-qa.yml", rf"^#   1\. `@v{V}` below is a TAG"),
    ("ci/estate-qa.yml", rf'pip install "git\+\S+\.git@v{V}"$'),
    ("ci/estate-pre-push", rf'pip install "git\+\S+\.git@v{V}"$'),
    ("docs/MANUAL.md", rf"^\*\*Version {V}\*\* · "),
    ("docs/MANUAL.md", rf'^pip install "git\+\S+\.git@v{V}"$'),
    ("docs/MANUAL.md", rf"kbqa --version +# must print {V}$"),
    ("docs/DEVELOPMENT.md", rf"^\*\*Version {V}\*\* · "),
    ("docs/README.md", rf"^https://\S+/kb-qa/v{V}/docs/MANUAL\.md$"),
    ("docs/pipeline.html", rf"<b>kbqa v{V}</b>"),
    ("llms.txt", rf"^\*\*Every link below is pinned to `v{V}`\*\*"),
    ("llms.txt", rf"^- \[[^\]]+\]\(https://\S+/kb-qa/(?:blob/)?v{V}/\S+\)"),
]

PREFLIGHT = "skills/kbqa-check/scripts/preflight.sh"
MANIFEST_PIN_RE = re.compile(r'^(EXPECTED_MANIFEST="\$\{KBQA_EXPECTED_MANIFEST:-)([0-9a-f]+)(\}")$', re.MULTILINE)
INIT = "src/kbqa/__init__.py"
CURRENT_RE = re.compile(r'^__version__ = "(\d+\.\d+\.\d+)"$', re.MULTILINE)
NAMES_PLACEHOLDER = "<file of names, one per line, kept outside the repository>"


class Refused(Exception):
    pass


def parse_version(text: str) -> Tuple[int, int, int]:
    m = VERSION_RE.match(text.strip())
    if not m:
        raise Refused(f"{text!r} is not a version (MAJOR.MINOR.PATCH)")
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def current_version(root: Path) -> str:
    m = CURRENT_RE.search((root / INIT).read_text(encoding="utf-8"))
    if not m:
        raise Refused(f"{INIT} declares no __version__")
    return m.group(1)


def _version_in(version: str) -> re.Pattern:
    """The version as a whole token: 6.2.1 is not inside 16.2.1 or 6.2.10."""
    return re.compile(r"(?<![\d.])" + re.escape(version) + r"(?!\.?\d)")


def plan_lines(root: Path, current: str, new: str) -> Tuple[Dict[str, str], List[dict]]:
    """({file: new text}, [{file, line, old, new}]) for the registered lines.
    Raises Refused when a pattern matches nothing or a matched line does not
    hold the current version."""
    token = _version_in(current)
    texts: Dict[str, str] = {}
    changes: List[dict] = []
    problems: List[str] = []
    for rel, pattern in VERSION_LINES:
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}: the file is missing")
            continue
        text = texts.get(rel)
        if text is None:
            text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        rx = re.compile(pattern)
        hits = 0
        for i, line in enumerate(lines):
            if not rx.search(line):
                continue
            hits += 1
            if not token.search(line):
                if any(c["file"] == rel and c["line"] == i + 1 for c in changes):
                    continue  # already bumped by an earlier pattern of the same file
                problems.append(f"{rel}:{i + 1}: a version line that does not hold {current}: {line.strip()}")
                continue
            lines[i] = token.sub(new, line)
            changes.append({"file": rel, "line": i + 1, "old": line, "new": lines[i]})
        if hits == 0:
            problems.append(f"{rel}: the pattern {pattern} matches no line — the registry or the file has drifted")
        texts[rel] = "\n".join(lines)
    if problems:
        raise Refused("the version lines are not as registered:\n  " + "\n  ".join(problems))
    return {rel: t for rel, t in texts.items() if t != (root / rel).read_text(encoding="utf-8")}, changes


def _load_manifest_module(root: Path):
    path = root / "src" / "kbqa" / "manifest.py"
    name = "_kbqa_release_manifest_" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise Refused(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def manifest_of(root: Path, new_texts: Optional[Dict[str, str]] = None) -> str:
    """The manifest digest the package at `root` will have once `new_texts`
    (repository-relative path -> text) are written — computed by the
    package's own manifest code."""
    mod = _load_manifest_module(root)
    files = dict(mod.compute_manifest())
    pkg = "src/kbqa/"
    for rel, text in (new_texts or {}).items():
        if rel.startswith(pkg) and rel[len(pkg):] in files:
            files[rel[len(pkg):]] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return mod.manifest_digest(files)


def repin(text: str, digest: str) -> Tuple[str, str]:
    """(new pre-flight text, the old pin). Exactly one pin, whole token."""
    pins = MANIFEST_PIN_RE.findall(text)
    if len(pins) != 1:
        raise Refused(f"{PREFLIGHT} must hold exactly one EXPECTED_MANIFEST line, found {len(pins)}")
    return MANIFEST_PIN_RE.sub(lambda m: m.group(1) + digest + m.group(3), text), pins[0][1]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def uncommitted(root: Path) -> List[str]:
    """Every path with uncommitted changes, untracked files included."""
    r = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                       capture_output=True)
    if r.returncode != 0:
        raise Refused(f"{root} is not a git working tree, so it cannot be shown to be clean: "
                      f"{r.stderr.decode(errors='replace').strip()}")
    out: List[str] = []
    parts = r.stdout.decode("utf-8", errors="replace").split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        out.append(path)
        if "R" in status or "C" in status:  # a rename or copy names its source next
            if i < len(parts) and parts[i]:
                out.append(parts[i])
            i += 1
    return sorted(set(out))


def left_alone(root: Path, current: str, changes: List[dict]) -> List[str]:
    """Every other tracked line that holds the current version — history notes —
    listed so the operator sees what was not changed. CHANGELOG.md is history
    throughout and is not listed."""
    r = _git(root, "ls-files", "-z")
    if r.returncode != 0:
        return []
    token = _version_in(current)
    bumped = {(c["file"], c["line"]) for c in changes}
    out = []
    for rel in sorted(p for p in r.stdout.split("\0") if p and p != "CHANGELOG.md"):
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.split("\n"), 1):
            if (rel, i) not in bumped and token.search(line):
                out.append(f"{rel}:{i}  {line.strip()}")
    return out


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        shutil.copymode(str(path), tmp)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _run(cmd: List[str], root: Path) -> Tuple[int, str]:
    r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).rstrip()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Bump every current-version line and the manifest pin.")
    ap.add_argument("version", help="the new version, MAJOR.MINOR.PATCH (a leading v is allowed)")
    ap.add_argument("--check", action="store_true", help="change nothing; report what would change")
    ap.add_argument("--root", default=str(ROOT), help="the repository (default: this script's)")
    ap.add_argument("--estate", default=os.environ.get("KBQA_ESTATE"),
                    help="the estate folder the private brand scan reads its names from (Requirements/brand_scan.py)")
    ap.add_argument("--names", default=os.environ.get("KBQA_BRAND_NAMES"),
                    help="for the printed brand scan: the file of names to look for (kept outside the repository)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    mode = "check" if args.check else "release"

    refusals: List[str] = []
    try:
        current = current_version(root)
        new_t = parse_version(args.version)
        new = ".".join(map(str, new_t))
        if new_t <= parse_version(current):
            raise Refused(f"{new} is not above the current version {current}")
        texts, changes = plan_lines(root, current, new)
        digest = manifest_of(root, texts)
        pre = texts.get(PREFLIGHT, (root / PREFLIGHT).read_text(encoding="utf-8"))
        texts[PREFLIGHT], old_pin = repin(pre, digest)
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 1

    dirty = []
    try:
        dirty = [p for p in uncommitted(root) if p not in texts]
    except Refused as exc:
        refusals.append(str(exc))
    if dirty:
        refusals.append("uncommitted changes outside the files this edits — commit or set them aside first:\n  "
                        + "\n  ".join(dirty))

    print(f"{mode}: {current} -> {new} in {root}")
    for c in changes:
        print(f"  {c['file']}:{c['line']}  {c['new'].strip()}")
    print(f"  {PREFLIGHT}  EXPECTED_MANIFEST {old_pin} -> {digest}")
    files = sorted({c["file"] for c in changes} | {PREFLIGHT})
    print(f"{len(changes)} version lines and 1 manifest pin, in {len(files)} files.")
    rest = left_alone(root, current, changes)
    if rest:
        print(f"Left as they are — {len(rest)} lines that mention {current} but are not current-version lines "
              "(history notes):")
        for line in rest:
            print(f"  {line}")
    changelog = root / "CHANGELOG.md"
    if changelog.is_file() and f"## [{new}]" not in changelog.read_text(encoding="utf-8"):
        print(f"NOTE: CHANGELOG.md has no '## [{new}]' entry yet; write it before tagging.")
    for r in refusals:
        print(f"REFUSED: {r}")
    if refusals:
        return 1
    if args.check:
        print("--check: nothing was changed.")
        return 0

    for rel in files:
        _write_atomic(root / rel, texts[rel])
    if manifest_of(root) != digest:
        print(f"FAILED: the manifest on disk is not {digest} after writing. Inspect: git -C \"{root}\" diff")
        return 1
    print(f"written: {len(files)} files.")

    py = sys.executable
    code, out = _run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(root / "tests")], root)
    print(f"suite: {(out.splitlines() or [''])[-1]}")
    if code != 0:
        print(out)
        print(f"FAILED: the suite does not pass. The bump is written; inspect it with git -C \"{root}\" diff.")
        return 1
    code, out = _run([py, str(root / "scripts" / "mutate.py"), "--root", str(root)], root)
    print(out)
    if code != 0:
        print(f"FAILED: the mutation registry does not pass. The bump is written; inspect it with git -C \"{root}\" diff.")
        return 1

    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "<branch>"
    names = args.names or NAMES_PLACEHOLDER
    tag = f"v{new}"
    print()
    print("Next, the operator, in their own terminal:")
    private_scan = root / "Requirements" / "brand_scan.py"
    if private_scan.is_file() and args.estate:
        # The agreed flow: the private scan over every changed file, then the push.
        print("  # after the commit: brand scan of every changed file (must print TOTAL 0), then push")
        print(f"  cd \"{root}\" && python3 Requirements/brand_scan.py \"{args.estate}\" "
              f"$(git diff --name-only main HEAD) && git push -u origin {branch}")
    else:
        print(f"  # brand scan — every published file; no output means none of the names appears")
        print(f"  git -C \"{root}\" grep -n -i -I -w -F -f \"{names}\"")
        print(f"  # commit, then push the branch and open its pull request")
        print(f"  git -C \"{root}\" push -u origin {branch}")
    print(f"  # once merged: tag the merged commit, push the tag, install from it, then audit")
    print(f"  git -C \"{root}\" tag {tag} <merged commit> && git -C \"{root}\" push origin {tag}")
    print(f"  bash \"{root}/scripts/audit.sh\" {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
