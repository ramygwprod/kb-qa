"""The manual must describe the tool that exists, not the one it described once.

Ten finding codes and two whole commands shipped without reaching the manual.
Nothing noticed, because a manual that omits something reads exactly like a
manual that is complete — the same shape as every defect recorded in
DECISIONS.md, committed against this package's own documentation.

An operator reads §6 to learn what they can run and §7 to learn what a finding
means. A code with no entry sends them to "see the message"; a command with no
entry does not exist as far as anyone reading is concerned.
"""

import re
from pathlib import Path

import pytest

from kbqa.report import REMEDIES

ROOT = Path(__file__).resolve().parent.parent
MANUAL = (ROOT / "docs" / "MANUAL.md").read_text(encoding="utf-8")
DEVELOPMENT = (ROOT / "docs" / "DEVELOPMENT.md").read_text(encoding="utf-8")
CLI = (ROOT / "src" / "kbqa" / "cli.py").read_text(encoding="utf-8")


def documented_codes(text: str):
    return set(re.findall(r"`([a-z][a-z0-9_]+)`", text))


@pytest.mark.parametrize("code", sorted(REMEDIES))
def test_every_finding_code_is_in_the_manual(code):
    assert f"`{code}`" in MANUAL, (
        f"{code!r} has a remedy but no entry in MANUAL §7. A reader who meets it "
        "in a report has nowhere to look it up."
    )


def test_the_manual_states_the_real_code_count():
    """A stated count that drifts is worse than none — it reads as verified."""
    m = re.search(r"(\d+) codes\. Every one carries a remedy", MANUAL)
    assert m, "MANUAL §7 no longer states how many codes there are"
    assert int(m.group(1)) == len(REMEDIES), (
        f"MANUAL says {m.group(1)} codes; there are {len(REMEDIES)}"
    )


def dispatched_commands():
    """Subcommands the CLI answers to, read from its dispatch rather than a list."""
    return set(re.findall(r'argv\[0\] == "([a-z][a-z0-9_-]*)"', CLI))


@pytest.mark.parametrize("command", sorted(dispatched_commands()))
def test_every_command_is_in_the_manual(command):
    assert re.search(rf"`{re.escape(command)}\b", MANUAL), (
        f"`{command}` is dispatched by the CLI and appears nowhere in the manual. "
        "A command nobody can find is a command nobody runs."
    )


@pytest.mark.parametrize("module", ["freeze", "mappings", "probe", "report", "sweep", "parsing"])
def test_every_top_level_module_is_in_the_module_map(module):
    assert f"`{module}.py`" in DEVELOPMENT, (
        f"{module}.py is missing from DEVELOPMENT's module map, so the next "
        "person extending this package will not know it exists."
    )


def test_these_guards_can_actually_fail():
    """A drift check that has never failed has not been tested."""
    assert "`definitely_not_a_real_code`" not in MANUAL
    assert not re.search(r"`definitely_not_a_command\b", MANUAL)


# --------------------------------------------------------------------------
# Nothing falls out of the index
# --------------------------------------------------------------------------

DOCS_DIR = ROOT / "docs"
DOCS_INDEX = (DOCS_DIR / "README.md").read_text(encoding="utf-8")
LLMS_TXT = (ROOT / "llms.txt").read_text(encoding="utf-8")


def doc_files():
    """Every document in docs/, except the index itself."""
    return sorted(p.name for p in DOCS_DIR.iterdir()
                  if p.is_file() and p.name != "README.md")


@pytest.mark.parametrize("name", doc_files())
def test_every_doc_is_in_the_index(name):
    """A document nobody can find is a document nobody reads.

    The failure this guards is not a broken link — it is a file added to docs/
    and never announced, which looks identical to a complete doc set. That is
    the same shape as every defect in DECISIONS.md.
    """
    assert name in DOCS_INDEX, (
        f"docs/{name} exists and docs/README.md never names it"
    )


@pytest.mark.parametrize("name", doc_files())
def test_every_doc_is_in_llms_txt(name):
    """The machine-readable index must not be a subset of the human one."""
    assert name in LLMS_TXT, (
        f"docs/{name} is absent from llms.txt, so an agent enumerating the "
        "documentation will not find it"
    )


def test_llms_txt_opens_the_way_the_convention_requires():
    """H1 project name, then a blockquote summary. Parsers rely on both."""
    lines = [l for l in LLMS_TXT.splitlines() if l.strip()]
    assert lines[0].startswith("# "), "llms.txt must open with an H1 project name"
    assert lines[1].startswith("> "), "llms.txt must follow the H1 with a blockquote summary"


def test_llms_txt_stays_an_index_not_a_manual():
    """The convention caps it near 2,000 words; past that it stops being read."""
    words = len(LLMS_TXT.split())
    assert words < 2000, f"llms.txt is {words} words — publish llms-full.txt instead"


def test_both_indexes_say_to_pin_the_version():
    """`main` moves. A session reading a newer manual than it runs is the drift
    this package spends its time catching elsewhere."""
    for name, text in (("docs/README.md", DOCS_INDEX), ("llms.txt", LLMS_TXT)):
        assert "main" in text and "version" in text.lower(), name
        assert "--version" in text, f"{name} never says how to find the installed version"


def test_the_index_guards_can_fail():
    assert "definitely-not-a-doc.md" not in DOCS_INDEX
    assert "definitely-not-a-doc.md" not in LLMS_TXT
