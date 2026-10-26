"""The release steps, as scripts: the mutation check, the version bump, the audit.

`scripts/mutate.py` breaks each registered guard and runs its tests;
`scripts/release.py` bumps every current-version line and the manifest pin;
`scripts/audit.sh` compares a fresh clone of a tag with what is installed.

Every case runs on a temporary copy: a small tree of its own, or a local git
repository standing in for the remote, and a temporary home. Nothing here
writes to the real repository or the real home folder.
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kbqa import __version__
from kbqa.manifest import MANIFEST_SHA256

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
PY = sys.executable
VENV_BIN = str(Path(sys.executable).parent)
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("bash", "git", "shasum")),
    reason="needs bash, git and shasum",
)


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_release_tooling_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


release = _load("release")
mutate = _load("mutate")


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV})


def _commit_all(root, msg="tree"):
    _git("-c", "user.name=t", "-c", "user.email=t@example.test", "add", "-A", cwd=root)
    _git("-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", msg, cwd=root)


def _snapshot(root):
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts}


def _next(version):
    major, minor, _ = (int(x) for x in version.split("."))
    return f"{major}.{minor + 1}.0"


NEW = _next(__version__)
# A history note: a version named as the point since or before which something holds.
HISTORY = re.compile(r"\b(since|before)\s+(kbqa\s+)?v?\d+\.\d+\.\d+", re.IGNORECASE)


# ── mutate.py ────────────────────────────────────────────────────────────────

PKG = "LIMIT = 3\n\n\ndef allowed(n):\n    return n <= LIMIT\n\n\ndef unguarded():\n    return 1\n"
TEST_PKG = "from pkg import allowed\n\n\ndef test_limit():\n    assert allowed(3) and not allowed(4)\n"


@pytest.fixture
def mtree(tmp_path):
    root = tmp_path / "m"
    (root / "tests").mkdir(parents=True)
    (root / "pkg.py").write_text(PKG)
    (root / "tests" / "test_pkg.py").write_text(TEST_PKG)
    return root


def _entry(label, old, new, tests=("tests/test_pkg.py",), file="pkg.py"):
    return {"label": label, "file": file, "old": old, "new": new, "tests": list(tests)}


def run_mutate(root, entries):
    reg = root.parent / "mutations.json"  # outside the tree
    reg.write_text(json.dumps(entries))
    return subprocess.run([PY, str(SCRIPTS / "mutate.py"), "--root", str(root), "--registry", str(reg)],
                          capture_output=True, text=True)


def test_mutate_reports_caught_missed_and_not_found_and_restores(mtree):
    before = _snapshot(mtree)
    r = run_mutate(mtree, [
        _entry("limit", "LIMIT = 3\n", "LIMIT = 4\n"),
        _entry("unguarded", "    return 1\n", "    return 2\n"),
        _entry("absent", "LIMIT = 9", "LIMIT = 8"),
        _entry("twice", "LIMIT", "CAP"),
    ])
    assert r.returncode == 1, r.stdout
    lines = r.stdout.splitlines()
    assert lines[0].startswith("CAUGHT") and "limit" in lines[0]
    assert lines[1].startswith("MISSED") and "unguarded" in lines[1]
    assert lines[2].startswith("NOT FOUND") and "0 times" in lines[2]
    assert lines[3].startswith("NOT FOUND") and "2 times" in lines[3]
    assert lines[-1] == "mutations: 4 — 1 caught, 1 missed, 2 not found, 0 error"
    assert _snapshot(mtree) == before, "every file is back, bytes and timestamps"


def test_mutate_passes_only_when_every_mutation_is_caught(mtree):
    r = run_mutate(mtree, [_entry("limit", "LIMIT = 3\n", "LIMIT = 4\n")])
    assert r.returncode == 0 and r.stdout.splitlines()[-1].endswith("1 caught, 0 missed, 0 not found, 0 error")


def test_a_test_run_that_cannot_run_is_never_counted_as_caught(mtree):
    """A syntax error fails pytest with exit 2: the guard was not tested."""
    r = run_mutate(mtree, [_entry("broken", "LIMIT = 3\n", "LIMIT = = 3\n")])
    assert r.returncode == 1 and r.stdout.startswith("ERROR")


def test_a_failing_baseline_applies_no_mutation(mtree):
    (mtree / "tests" / "test_pkg.py").write_text("def test_no():\n    assert False\n")
    before = _snapshot(mtree)
    r = run_mutate(mtree, [_entry("limit", "LIMIT = 3\n", "LIMIT = 4\n")])
    assert r.returncode == 1
    assert "BASELINE FAILS" in r.stdout and "No mutation was applied" in r.stdout
    assert "CAUGHT" not in r.stdout and _snapshot(mtree) == before


def test_the_file_is_restored_when_the_test_run_raises(mtree):
    before = (mtree / "pkg.py").read_bytes()
    with pytest.raises(OSError):
        mutate.mutate_one(mtree, _entry("limit", "LIMIT = 3\n", "LIMIT = 4\n"), "/nonexistent/python")
    assert (mtree / "pkg.py").read_bytes() == before


@pytest.mark.parametrize("bad, why", [
    ({"label": "x", "file": "pkg.py", "old": "a", "tests": ["t"]}, "exactly the keys"),
    (_entry("x", "a", "a"), "differs from old"),
    (_entry("x", "a", "b", tests=()), "non-empty list"),
    (_entry("x", "a", "b", file="../outside.py"), "outside"),
])
def test_a_malformed_registry_is_refused(mtree, bad, why):
    before = _snapshot(mtree)
    r = run_mutate(mtree, [bad])
    assert r.returncode == 1 and r.stdout.startswith("REFUSED") and why in r.stdout
    assert _snapshot(mtree) == before


# ── release.py ───────────────────────────────────────────────────────────────

NOTES = (f"Since v{__version__} the capture keeps chrome once.\n"
         f"Receipts written before kbqa {__version__} carry no hash.\n"
         f"(since\n  v{__version__}). Wrapped.\n")


@pytest.fixture
def rtree(tmp_path):
    """The version-bearing files of this repository, the package source (for the
    manifest), both scripts, a one-test suite and a one-entry mutation registry,
    committed in a git repository of its own."""
    root = tmp_path / "r"
    wanted = {rel for rel, _ in release.VERSION_LINES} | {release.PREFLIGHT, "scripts/release.py", "scripts/mutate.py"}
    for rel in wanted:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, root / rel)
    for p in list((REPO_ROOT / "src" / "kbqa").glob("*.py")) + list((REPO_ROOT / "src" / "kbqa" / "gates").glob("*.py")):
        dst = root / p.relative_to(REPO_ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    (root / "docs" / "NOTES.md").write_text(NOTES)
    with open(root / "docs" / "MANUAL.md", "a", encoding="utf-8") as fh:
        fh.write(f"\nsince v{__version__}, the pre-flight checks the agents too.\n")
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{NEW}] — today\n")
    (root / "guard.py").write_text("def ok():\n    return True\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_guard.py").write_text("from guard import ok\n\n\ndef test_ok():\n    assert ok()\n")
    (root / "tests" / "mutations.json").write_text(json.dumps([
        {"label": "guard", "file": "guard.py", "old": "return True", "new": "return False",
         "tests": ["tests/test_guard.py"]}]))
    shutil.copy2(REPO_ROOT / ".gitignore", root / ".gitignore")  # as a real checkout ignores caches
    _git("init", "-q", cwd=root)
    _commit_all(root)
    return root


def run_release(root, *args):
    return subprocess.run([PY, str(root / "scripts" / "release.py"), *args, "--root", str(root)],
                          capture_output=True, text=True, env={**os.environ, **GIT_ENV})


def _status(root):
    return _git("status", "--porcelain", cwd=root).stdout.splitlines()


def test_check_changes_nothing_and_reports_every_line(rtree):
    before = _snapshot(rtree)
    r = run_release(rtree, NEW, "--check")
    assert r.returncode == 0, r.stdout
    assert "--check: nothing was changed." in r.stdout
    for rel in {rel for rel, _ in release.VERSION_LINES}:
        assert f"  {rel}:" in r.stdout, rel
    assert f"EXPECTED_MANIFEST {MANIFEST_SHA256} -> " in r.stdout
    assert "Left as they are" in r.stdout and "docs/NOTES.md:1" in r.stdout
    assert _snapshot(rtree) == before and _status(rtree) == []


def test_release_bumps_exactly_the_version_lines_and_repins(rtree):
    old = {p: p.read_text(encoding="utf-8") for p in rtree.rglob("*")
           if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts}
    r = run_release(rtree, NEW)
    assert r.returncode == 0, r.stdout + r.stderr
    changed_files = set()
    for p, text in old.items():
        now = p.read_text(encoding="utf-8")
        if now == text:
            continue
        changed_files.add(p.relative_to(rtree).as_posix())
        a, b = text.split("\n"), now.split("\n")
        assert len(a) == len(b)
        for x, y in zip(a, b):
            if x != y:
                assert __version__ in x or "EXPECTED_MANIFEST" in x, x
                assert not HISTORY.search(x), f"a history note changed: {x}"
    assert changed_files == {rel for rel, _ in release.VERSION_LINES} | {release.PREFLIGHT}
    assert (rtree / "docs" / "NOTES.md").read_text() == NOTES
    assert f"since v{__version__}, the pre-flight" in (rtree / "docs" / "MANUAL.md").read_text()
    pre = (rtree / release.PREFLIGHT).read_text()
    assert re.findall(r'^PINNED="\$\{KBQA_PINNED:-v(\S+)\}"$', pre, re.M) == [NEW]
    computed = subprocess.run([PY, "-c", "import importlib.util,sys;"
                               "s=importlib.util.spec_from_file_location('m',sys.argv[1]);"
                               "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(m.MANIFEST_SHA256)",
                               str(rtree / "src" / "kbqa" / "manifest.py")],
                              capture_output=True, text=True).stdout.strip()
    assert re.findall(r'KBQA_EXPECTED_MANIFEST:-([0-9a-f]+)\}', pre) == [computed] and computed != MANIFEST_SHA256
    assert f'__version__ = "{NEW}"' in (rtree / "src" / "kbqa" / "__init__.py").read_text()
    assert f"**This copy is kbqa-collect v{NEW}**" in (rtree / "skills" / "kbqa-collect" / "SKILL.md").read_text()
    assert "suite: 1 passed" in r.stdout and "mutations: 1 — 1 caught" in r.stdout
    assert f'grep -n -i -I -w -F -f' in r.stdout and "push -u origin" in r.stdout
    assert f"scripts/audit.sh\" v{NEW}" in r.stdout


def test_release_prints_the_agreed_brand_scan_and_push_when_the_private_scan_exists(rtree):
    (rtree / ".gitignore").write_text("Requirements/\n")
    _commit_all(rtree, "ignore the private folder")
    (rtree / "Requirements").mkdir()
    (rtree / "Requirements" / "brand_scan.py").write_text("")
    r = run_release(rtree, NEW, "--estate", "/the/estate")
    assert r.returncode == 0, r.stdout + r.stderr
    assert ('python3 Requirements/brand_scan.py "/the/estate" $(git diff --name-only main HEAD) '
            "&& git push -u origin") in r.stdout
    assert "grep -n -i -I -w -F -f" not in r.stdout


@pytest.mark.parametrize("dirty", ["untracked", "tracked"])
def test_release_refuses_uncommitted_changes_outside_its_files(rtree, dirty):
    if dirty == "untracked":
        (rtree / "notes.txt").write_text("x\n")
    else:
        (rtree / "guard.py").write_text("def ok():\n    return 1\n")
    before = _snapshot(rtree)
    r = run_release(rtree, NEW)
    assert r.returncode == 1 and "uncommitted changes outside the files this edits" in r.stdout
    assert ("notes.txt" if dirty == "untracked" else "guard.py") in r.stdout
    assert _snapshot(rtree) == before


def test_release_accepts_uncommitted_changes_in_its_own_files(rtree):
    with open(rtree / "pyproject.toml", "a") as fh:
        fh.write("# a local note\n")
    r = run_release(rtree, NEW, "--check")
    assert r.returncode == 0, r.stdout


def test_release_refuses_a_version_not_above_the_current_one(rtree):
    r = run_release(rtree, __version__, "--check")
    assert r.returncode == 1 and "is not above the current version" in r.stdout


def test_release_refuses_a_registered_line_holding_another_version(rtree):
    m = rtree / "docs" / "MANUAL.md"
    m.write_text(m.read_text().replace(f'kb-qa.git@v{__version__}"', 'kb-qa.git@v1.2.3"', 1))
    _commit_all(rtree, "drift")
    before = _snapshot(rtree)
    r = run_release(rtree, NEW)
    assert r.returncode == 1 and "does not hold" in r.stdout and "docs/MANUAL.md" in r.stdout
    assert _snapshot(rtree) == before


def test_release_refuses_a_pattern_that_matches_nothing(rtree):
    s = rtree / "skills" / "README.md"
    s.write_text(s.read_text().replace(f"bash skills/install.sh v{__version__}", "bash skills/install.sh <tag>"))
    _commit_all(rtree, "drift")
    r = run_release(rtree, NEW, "--check")
    assert r.returncode == 1 and "matches no line" in r.stdout and "skills/README.md" in r.stdout


def test_release_stops_when_a_mutation_is_missed(rtree):
    (rtree / "tests" / "mutations.json").write_text(json.dumps([
        {"label": "nothing guards this", "file": "guard.py", "old": "def ok():", "new": "def ok(): # x",
         "tests": ["tests/test_guard.py"]}]))
    _commit_all(rtree, "a weak registry")
    r = run_release(rtree, NEW)
    assert r.returncode == 1 and "MISSED" in r.stdout and "FAILED: the mutation registry" in r.stdout


def test_the_registry_matches_this_repository_and_no_history_note():
    """Read only: the registry finds every current-version line here, and none
    of the lines it would change is a history note."""
    texts, changes = release.plan_lines(REPO_ROOT, __version__, NEW)
    assert {c["file"] for c in changes} == {rel for rel, _ in release.VERSION_LINES}
    for c in changes:
        assert not HISTORY.search(c["old"]), c
    assert release.manifest_of(REPO_ROOT) == MANIFEST_SHA256, "the script computes the package's own manifest"


def test_the_manifest_pin_is_replaced_as_a_whole_token():
    text = 'x\nEXPECTED_MANIFEST="${KBQA_EXPECTED_MANIFEST:-' + "a" * 65 + '}"\ny\n'
    new, old = release.repin(text, "b" * 64)
    assert old == "a" * 65
    assert new == 'x\nEXPECTED_MANIFEST="${KBQA_EXPECTED_MANIFEST:-' + "b" * 64 + '}"\ny\n'
    with pytest.raises(release.Refused):
        release.repin(text + text, "b" * 64)


def test_a_version_is_matched_as_a_whole_token():
    rx = release._version_in("6.2.1")
    assert rx.search("v6.2.1.") and rx.search("@v6.2.1\"")
    assert not rx.search("16.2.1") and not rx.search("6.2.10") and not rx.search("6.2.1.3")


# ── audit.sh ─────────────────────────────────────────────────────────────────

TAG = f"v{__version__}"


@pytest.fixture
def aworld(tmp_path):
    """A local bare repository as the remote, holding this tree's skills, agents
    and package source at a tag; the skills installed from it into a temporary
    home with install.sh, as the operator does."""
    origin = tmp_path / "origin"
    shutil.copytree(REPO_ROOT / "skills", origin / "skills", ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
    shutil.copytree(REPO_ROOT / "agents", origin / "agents", ignore=shutil.ignore_patterns(".DS_Store"))
    shutil.copytree(REPO_ROOT / "src" / "kbqa", origin / "src" / "kbqa",
                    ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
    pre = origin / release.PREFLIGHT
    # The tag pins the manifest of the code it holds (between releases the
    # working tree's pin may be stale; that is the release's job, not this test's).
    pre.write_text(re.sub(r"(KBQA_EXPECTED_MANIFEST:-)[0-9a-f]+", r"\g<1>" + MANIFEST_SHA256, pre.read_text()))
    _git("init", "-q", cwd=origin)
    _commit_all(origin, "release")
    _git("tag", TAG, cwd=origin)
    _git("branch", "-q", "a-branch", cwd=origin)
    bare = tmp_path / "remote.git"
    _git("clone", "-q", "--bare", str(origin), str(bare), cwd=tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "tmp").mkdir()
    w = {"origin": origin, "bare": bare, "home": home, "tmp": tmp_path / "tmp",
         "skills": home / ".claude" / "skills", "agents": home / ".claude" / "agents"}
    r = subprocess.run(["bash", str(REPO_ROOT / "skills" / "install.sh"), TAG], env=_aenv(w),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return w


def _aenv(w, path=None):
    return {"HOME": str(w["home"]), "PATH": path or f"{VENV_BIN}:/usr/bin:/bin", "TMPDIR": str(w["tmp"]),
            "KBQA_REPO": f"file://{w['bare']}", "KBQA_SKILLS_HOME": str(w["skills"]),
            "KBQA_AGENTS_HOME": str(w["agents"]), "KBQA_BACKUP_DIR": str(w["home"] / "backups"), **GIT_ENV}


def audit(w, tag=TAG, path=None):
    return subprocess.run(["bash", str(SCRIPTS / "audit.sh"), tag], env=_aenv(w, path),
                          capture_output=True, text=True)


def _unlock(path):
    subprocess.run(["chmod", "-R", "u+w", str(path)], check=True)


def test_audit_passes_on_what_was_installed_from_the_tag(aworld):
    r = audit(aworld)
    lines = r.stdout.splitlines()
    assert r.returncode == 0, r.stdout
    assert len(lines) == 8 and all(ln.startswith("OK ") for ln in lines[:7]), lines
    assert lines[-1].startswith(f"AUDIT PASS: {TAG}") and lines[-1].endswith("7 of 7 OK")
    assert list(aworld["tmp"].iterdir()) == [], "the clone is removed"


@pytest.mark.parametrize("change, expect", [
    ("edited", "changed: SKILL.md"),
    ("added", "not in the tag: extra rules.md"),
    ("removed", "missing: SKILL.md"),
])
def test_audit_finds_a_changed_skill(aworld, change, expect):
    d = aworld["skills"] / "kbqa-check"
    _unlock(d)
    if change == "edited":
        (d / "SKILL.md").write_text((d / "SKILL.md").read_text() + "\nOne more rule.\n")
    elif change == "added":
        (d / "extra rules.md").write_text("Also do this.\n")
    else:
        (d / "SKILL.md").unlink()
    r = audit(aworld)
    assert r.returncode == 1
    assert any(ln.startswith("DIFF skill kbqa-check:") and expect in ln for ln in r.stdout.splitlines()), r.stdout
    assert r.stdout.splitlines()[-1].endswith("1 of 7 DIFF")


def test_audit_finds_an_edited_agent(aworld):
    a = aworld["agents"] / "kbqa-row-writer.md"
    _unlock(a)
    a.write_text(a.read_text() + "\nYou may also fetch.\n")
    r = audit(aworld)
    assert r.returncode == 1
    assert any(ln.startswith("DIFF agents:") and "kbqa-row-writer.md" in ln for ln in r.stdout.splitlines()), r.stdout


def test_audit_finds_another_tag_installed(aworld):
    _git("tag", "v0.0.1", cwd=aworld["origin"])
    _git("push", "-q", str(aworld["bare"]), "v0.0.1", cwd=aworld["origin"])
    r = audit(aworld, "v0.0.1")
    out = r.stdout.splitlines()
    assert r.returncode == 1
    assert [ln.split()[0] for ln in out[:7]] == ["OK", "OK", "OK", "OK", "DIFF", "DIFF", "OK"], out
    assert "tag " + TAG in out[4] and "the tag is v0.0.1" in out[5]


def test_audit_finds_a_tag_whose_pin_is_not_its_code(aworld):
    pre = aworld["origin"] / release.PREFLIGHT
    pre.write_text(re.sub(r"(KBQA_EXPECTED_MANIFEST:-)[0-9a-f]+", r"\g<1>" + "0" * 64, pre.read_text()))
    _commit_all(aworld["origin"], "a stale pin")
    _git("tag", "v0.0.2", cwd=aworld["origin"])
    _git("push", "-q", str(aworld["bare"]), "v0.0.2", cwd=aworld["origin"])
    r = audit(aworld, "v0.0.2")
    line7 = r.stdout.splitlines()[6]
    assert r.returncode == 1 and line7.startswith("DIFF package code:") and "pin " + "0" * 64 in line7


def test_audit_refuses_a_ref_that_is_not_a_tag(aworld):
    r = audit(aworld, "a-branch")
    assert r.returncode == 2 and r.stdout.startswith("AUDIT REFUSED:") and "not a tag" in r.stdout


def test_audit_refuses_when_the_remote_cannot_be_read(aworld):
    shutil.rmtree(aworld["bare"])
    r = audit(aworld)
    assert r.returncode == 2 and r.stdout.startswith("AUDIT REFUSED:")


def test_audit_refuses_when_the_package_cannot_be_found(aworld):
    if subprocess.run(["/usr/bin/python3", "-m", "kbqa", "--version"], capture_output=True).returncode == 0:
        pytest.skip("/usr/bin/python3 has kbqa installed here")
    r = audit(aworld, path="/usr/bin:/bin")
    assert r.returncode == 2 and r.stdout.startswith("AUDIT REFUSED: kbqa cannot be imported")


def test_loading_the_manifest_writes_no_bytecode(tmp_path):
    # CI's interpreter writes bytecode next to the source (a macOS framework
    # Python writes it to a cache folder instead, so a filesystem test passes
    # there either way). A release tool that leaves __pycache__ in the tree it
    # then checks for uncommitted changes refuses its own run — so loading the
    # manifest must happen with bytecode writing off, on every interpreter.
    src = tmp_path / "src" / "kbqa"
    src.mkdir(parents=True)
    (src / "manifest.py").write_text("import sys\nWRITING_OFF = sys.dont_write_bytecode\nMANIFEST_SHA256 = 'x'\n")
    before = sys.dont_write_bytecode
    mod = release._load_manifest_module(tmp_path)
    assert mod.WRITING_OFF is True
    assert sys.dont_write_bytecode == before, "the interpreter's own setting is restored"
