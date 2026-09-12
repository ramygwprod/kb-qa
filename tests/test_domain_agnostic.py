"""Proof that the gates are not bound to one domain.

The claim being tested: this tool collects market intelligence in **any**
sector, and nothing about the subjects already collected constrains what can be
collected next.

That is easy to assert and easy to get wrong, because the failure is invisible
from inside the original domain — every test passes, and the tool only breaks
when someone tries a second sector. So the test defines a profile for a
genuinely different subject (regulatory compliance posture: obligations,
enforcement, jurisdictions — not a feature or a mechanism in sight) and runs
the real gates against it.

If the gates carry any assumption about vendors, features, or product
hierarchies, this file fails.
"""

import json
import os
from enum import Enum
from typing import Optional

import pytest
from pydantic import Field

from kbqa import profile as profile_mod
from kbqa.conventions import Conventions
from kbqa.extensions import PROVENANCE, VERBATIM, ext
from kbqa.gates import g1_capture, g2_conformance, g3_grounding
from kbqa.models import CoreRow
from kbqa.profile import Profile
from kbqa.verdict import FAIL, PASS

CAPTURE_MTIME = 1_000_000_000
STAGING_MTIME = 1_000_000_100


# --------------------------------------------------------------------------
# A profile for an entirely different domain
# --------------------------------------------------------------------------

class Obligation(str, Enum):
    """Nothing to do with software features."""
    mandatory = "mandatory"
    conditional = "conditional"
    advisory = "advisory"
    exempt = "exempt"


class SourceAuthority(str, Enum):
    """This domain grades sources on a different axis entirely."""
    statute = "statute"
    regulation = "regulation"
    guidance = "guidance"
    enforcement_action = "enforcement-action"


class ComplianceRow(CoreRow):
    source_authority: SourceAuthority
    certainty: int = Field(ge=1, le=5)
    obligation: Obligation
    jurisdiction: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    penalty_stated: bool = False
    supersedes: Optional[str] = None


COMPLIANCE_EXTENSIONS = {
    "regulator_term": ext(VERBATIM, None,
                          "The regulator's own name for the obligation, in "
                          "their wording rather than ours."),
    "citation_style": ext(PROVENANCE, "instrument",
                          "How the instrument was cited on the page we read."),
}

COMPLIANCE_CONVENTIONS = Conventions(
    staging_glob="**/rows-*.md",
    staging_prefix="rows-",
    staging_suffix=".md",
    capture_template="pages-{batch}.txt",
    capture_glob="pages-*.txt",
    begin_pattern=r"^<<< PAGE (?P<url>.+?) >>>$",
    end_pattern=r"^<<< END (?P<url>.+?) >>>$",
    verdict_dir="_checks",
)


@pytest.fixture
def compliance_profile():
    """Register the profile, activate it, and restore afterwards."""
    name = "compliance-posture"
    if name not in profile_mod.available():
        profile_mod.register(Profile(
            name=name,
            description="Regulatory obligations by jurisdiction and instrument.",
            row_model=ComplianceRow,
            extensions=COMPLIANCE_EXTENSIONS,
            conventions=COMPLIANCE_CONVENTIONS,
        ))
    previous = profile_mod.active().name
    profile_mod.activate(name)
    yield profile_mod.active()
    profile_mod.activate(previous)


URL = "https://rules.example.test/aml/reporting"
QUOTE = "Reporting entities must file a report within ten business days."


def _row(**kw):
    base = dict(
        id="aml.reporting.deadline",
        source_url=URL,
        source_quote=QUOTE,
        access_date="2026-09-12",
        source_authority="statute",
        certainty=5,
        obligation="mandatory",
        jurisdiction="EX",
        instrument="Example AML Act s.12",
    )
    base.update(kw)
    return base


@pytest.fixture
def corpus(tmp_path, compliance_profile):
    """A corpus using this domain's conventions — different names, different
    marker syntax, nothing in common with the other profile's layout."""
    c = compliance_profile.conventions
    d = tmp_path / "corpus" / "EX-regulator"
    d.mkdir(parents=True)

    capture = d / c.capture_for("aml")
    capture.write_text(
        f"<<< PAGE {URL} >>>\n"
        f"Filing deadlines\n\n{QUOTE}\n"
        f"<<< END {URL} >>>\n",
        encoding="utf-8",
    )
    staging = d / c.staging_for("aml")
    staging.write_text(
        "---\nbatch: aml\n---\n\n# rows\n\n"
        + json.dumps(_row()) + "\n",
        encoding="utf-8",
    )
    os.utime(capture, (CAPTURE_MTIME, CAPTURE_MTIME))
    os.utime(staging, (STAGING_MTIME, STAGING_MTIME))
    return staging, capture


# --------------------------------------------------------------------------
# The gates must work with no knowledge of the domain
# --------------------------------------------------------------------------

def test_a_foreign_domain_row_validates(compliance_profile):
    r = ComplianceRow(**_row())
    assert r.obligation == Obligation.mandatory
    assert r.source_quote == QUOTE


def test_no_field_from_the_other_profile_is_required(compliance_profile):
    """`mechanism`, `outcome`, `depth_level`, `vendor_term` must be absent.

    If any survived into the core, every other domain would have to invent a
    value for a question its sector does not ask.
    """
    fields = set(ComplianceRow.model_fields)
    for leaked in ("mechanism", "outcome", "depth_level", "vendor_term",
                   "what_it_does", "canonical", "evidence_grade", "confidence"):
        assert leaked not in fields, f"{leaked} leaked into the universal core"


def test_grounding_works_in_a_foreign_domain(corpus):
    """G3 is the correctness gate. It must not care what is being studied."""
    staging, capture = corpus
    v, code = g3_grounding.run(["--staging", str(staging), "--capture", str(capture)])
    assert v.verdict == PASS, v.findings
    assert v.counts["grounded"] == 1


def test_grounding_still_catches_invention_in_a_foreign_domain(corpus):
    """The guarantee has to survive the move, not just the happy path."""
    staging, _ = corpus
    text = staging.read_text().replace(
        QUOTE, "Reporting entities must file a report immediately.")
    staging.write_text(text, encoding="utf-8")
    os.utime(staging, (STAGING_MTIME, STAGING_MTIME))

    v, code = g3_grounding.run([
        "--staging", str(staging),
        "--capture", str(staging.parent / "pages-aml.txt"),
    ])
    assert v.verdict == FAIL
    assert "quote_not_in_capture" in {f.code for f in v.findings}


def test_conformance_works_in_a_foreign_domain(corpus):
    staging, _ = corpus
    v, code = g2_conformance.run(["--staging", str(staging)])
    assert v.verdict == PASS, v.findings
    assert v.counts["rows"] == 1


def test_conformance_still_refuses_an_unregistered_field(corpus):
    """The §2 guarantee must hold in every domain, not just the first."""
    staging, _ = corpus
    row = _row()
    row["invented_here"] = "x"
    staging.write_text(
        "---\nbatch: aml\n---\n\n# rows\n\n" + json.dumps(row) + "\n",
        encoding="utf-8")

    v, _ = g2_conformance.run(["--staging", str(staging)])
    assert v.verdict == FAIL
    assert "schema_violation" in {f.code for f in v.findings}


def test_this_domains_registered_extension_is_accepted(corpus):
    staging, _ = corpus
    row = _row(regulator_term="Suspicious Matter Report")
    staging.write_text(
        "---\nbatch: aml\n---\n\n# rows\n\n" + json.dumps(row) + "\n",
        encoding="utf-8")

    v, _ = g2_conformance.run(["--staging", str(staging)])
    assert v.verdict == PASS, v.findings


def test_custom_capture_markers_are_honoured(corpus, compliance_profile):
    """This corpus delimits pages with `<<< PAGE … >>>`, not `=====BEGIN=====`.

    Compiling one programme's marker syntax into the parser meant a corpus that
    delimited differently parsed to zero page blocks — and zero blocks reads as
    "nothing to check against", not as "wrong syntax".
    """
    _, capture = corpus
    from kbqa.parsing import parse_capture

    cap = parse_capture(capture)
    assert len(cap.blocks) == 1, "custom markers must be read from the profile"
    assert URL in cap.blocks
    assert not cap.marker_errors


def test_custom_file_naming_is_honoured(compliance_profile):
    c = compliance_profile.conventions
    assert c.staging_for("aml") == "rows-aml.md"
    assert c.capture_for("aml") == "pages-aml.txt"
    assert c.batch_of("rows-aml.md") == "aml"


def test_switching_profiles_switches_the_contract(compliance_profile):
    """Two profiles, two contracts, no leakage between them."""
    assert "obligation" in profile_mod.row_model().model_fields

    profile_mod.activate("vendor-catalogue")
    assert "obligation" not in profile_mod.row_model().model_fields
    assert "mechanism" in profile_mod.row_model().model_fields

    profile_mod.activate("compliance-posture")
    assert "mechanism" not in profile_mod.row_model().model_fields


# --------------------------------------------------------------------------
# Anti-drift: the core must stay universal
# --------------------------------------------------------------------------

UNIVERSAL = {
    "schema_version",   # which contract this row was written against
    "id",               # addresses one claim
    "source_url",       # where it came from
    "source_quote",     # the verbatim evidence
    "access_date",      # when it was seen
    "broken_source",    # whether the source still resolves
}


def test_the_core_contains_only_universal_fields():
    """Pinned so methodology cannot drift back into the core.

    This is the failure that does not announce itself. Adding a field here
    costs nothing today and breaks the NEXT domain — which nobody is testing
    when they add it. Every field below must be answerable without knowing what
    is being studied.

    If this fails, the question is not "update the test". It is: does a labour
    market, a regulator and a software vendor all have this? If not, it belongs
    in a profile.
    """
    actual = set(CoreRow.model_fields)
    extra = actual - UNIVERSAL
    missing = UNIVERSAL - actual
    assert not extra, (
        f"non-universal field(s) in the core: {sorted(extra)}. "
        "Ask whether every domain has this; if not, move it to a profile."
    )
    assert not missing, f"universal field(s) removed from the core: {sorted(missing)}"


def test_no_profile_enum_is_importable_from_the_core():
    """Vocabulary lives in profiles, not in the shared module."""
    import kbqa.models as m
    for leaked in ("EvidenceGrade", "Mechanism", "Outcome", "DepthLevel"):
        assert not hasattr(m, leaked), (
            f"{leaked} is in models.py — that makes one programme's vocabulary "
            "the standard for every domain"
        )


def test_the_id_pattern_is_a_convention_not_a_law():
    """A programme addressing nodes differently is different, not malformed."""
    from kbqa.conventions import Conventions
    assert Conventions().id_pattern, "the default must still exist"
    uuidish = Conventions(id_pattern=r"^[0-9a-f\-]{36}$")
    assert uuidish.id_pattern != Conventions().id_pattern


def test_registries_do_not_leak_between_profiles(compliance_profile):
    """A field registered for one domain must not be accepted in another.

    Otherwise the first corpus collected quietly sets what later ones may say.
    """
    assert "node_kind" not in profile_mod.active().extensions
    assert "regulator_term" in profile_mod.active().extensions

    profile_mod.activate("vendor-catalogue")
    assert "regulator_term" not in profile_mod.active().extensions
    assert "node_kind" in profile_mod.active().extensions
