"""The mutation registry itself: well formed, and current with the code.

Kept apart from the tests of the scripts: while `scripts/mutate.py` runs a
mutation, the mutated file no longer holds that entry's `old` text, so a check
of the registry run inside the mutation would fail for that reason alone and
make every mutation look caught.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("_registry_mutate", REPO_ROOT / "scripts" / "mutate.py")
mutate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutate)


def test_the_real_registry_is_well_formed_and_each_old_text_occurs_once():
    """Read only: the seeded guards still exist exactly as registered."""
    entries = mutate.load_registry(REPO_ROOT / "tests" / "mutations.json")
    for e in entries:
        text = (REPO_ROOT / e["file"]).read_text(encoding="utf-8")
        assert text.count(e["old"]) == 1, e["label"]
        for t in e["tests"]:
            assert (REPO_ROOT / t.split("::")[0]).is_file(), (e["label"], t)
