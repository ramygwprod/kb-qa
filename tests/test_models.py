"""The contract: universal core, profile framework, verbatim subject fields.

The load-bearing property is that BOTH halves still hold. It is easy to open a
schema up and lose the guarantee that made it worth having; it is equally easy
to keep it closed and reject vendors for having their own vocabulary. These
tests pin both edges.
"""

import pytest

from kbqa.extensions import ANNOTATION, BATCH_LEVEL, PROVENANCE, VERBATIM
from kbqa.models import CoreRow, SCHEMA_VERSION
from kbqa.profile import active, row_model
from kbqa.profiles.vendor_catalogue import DepthLevel, EvidenceGrade

Row = row_model()
REGISTRY = active().extensions

CORE = dict(
    id="acme.widgets",
    vendor_term="Widgets",
    what_it_does="Compose reusable UI blocks.",
    source_url="https://docs.acme.test/widgets",
    source_quote="Acme Widgets let you compose reusable UI blocks.",
    access_date="2026-08-23",
    evidence_grade="official-doc",
    confidence="high",
    mechanism="Native",
    outcome="yes",
    depth_level="feature",
)


def row(**kw):
    return Row(**{**CORE, **kw})


# --------------------------------------------------------------------------
# The guarantee that must survive opening the schema
# --------------------------------------------------------------------------

def test_an_invented_field_is_still_rejected():
    """`extra="forbid"` moved; it did not go away.

    This is the §2 guarantee: a collector cannot grow the schema at runtime.
    """
    with pytest.raises(Exception) as e:
        row(confidence_note="pretty sure")
    assert "unregistered field" in str(e.value)
    assert "confidence_note" in str(e.value)


def test_the_rejection_says_how_to_resolve_it():
    """A refusal that does not say what to do next just gets worked around."""
    with pytest.raises(Exception) as e:
        row(some_new_idea="x")
    msg = str(e.value)
    assert "profile" in msg, "the refusal must name where to register the field"
    assert "stop emitting it" in msg


@pytest.mark.parametrize("field", ["node_kind", "vendor_category", "mechanism_raw"])
def test_a_registered_vendor_field_is_accepted(field):
    r = row(**{field: "whatever the vendor said"})
    assert getattr(r, field) == "whatever the vendor said"


def test_registered_field_values_are_never_constrained():
    """The NAME is declared; the VALUE is the vendor's business.

    An enum drawn from the vendors collected first would reject the next
    vendor's vocabulary as invalid — editing evidence to fit our model.
    """
    for value in ["A_SHORT_TOKEN", "SOMETHING_NOBODY_HAS_SEEN",
                  "a long free-text elaboration the vendor chose to write"]:
        assert row(node_kind=value).node_kind == value


# --------------------------------------------------------------------------
# Vendor structure is evidence
# --------------------------------------------------------------------------

@pytest.mark.parametrize("depth", ["product-line", "module", "sub-module", "feature", "sub-feature"])
def test_named_depth_levels_are_accepted(depth):
    assert row(depth_level=depth).depth_level == depth


@pytest.mark.parametrize("depth", ["2", "3", "4", "5", "6"])
def test_numeric_depth_is_accepted(depth):
    """Some vendors' hierarchies do not fit five names.

    A numeric depth records position in THAT vendor's tree. Forcing the named
    levels would flatten a real structural difference into a false one.
    """
    assert row(depth_level=depth).depth_level == depth


@pytest.mark.parametrize("depth", [2, 3, 4, 5, 6])
def test_numeric_depth_is_accepted_as_an_integer_too(depth):
    """Regression: 170 rows rejected on TYPE before the validator ran.

    The collector writes numeric depth as a JSON integer. Declaring the field
    `str` made numeric depth work only if it happened to be quoted — a
    distinction the data does not draw.
    """
    assert row(depth_level=depth).depth_level == str(depth)


def test_depth_level_still_rejects_nonsense():
    """Open to two conventions is not open to anything."""
    with pytest.raises(Exception) as e:
        row(depth_level="quite deep")
    assert "neither a named level" in str(e.value)


def test_both_evidence_grade_spellings_are_accepted():
    """Our field, our enum — but rejecting rows over brackets taught nothing."""
    assert row(evidence_grade="verify").evidence_grade == EvidenceGrade.verify
    assert row(evidence_grade="[verify]").evidence_grade == EvidenceGrade.verify_bracketed


def test_an_unknown_evidence_grade_is_still_rejected():
    with pytest.raises(Exception):
        row(evidence_grade="blog")


@pytest.mark.parametrize("ident", [
    "acme.products.net.a2p_monetization",   # underscore — 857 rows failed on this
    "acme",                                  # single segment — 47 rows failed
    "a.b.c.d.e.f",                           # six segments, as the estate uses
    "acme.widgets-pro.v2",                   # hyphens and digits still fine
])
def test_real_id_shapes_are_accepted(ident):
    """Regression: 904 rows rejected by an invented id pattern.

    857 contained `_`, which v1 permitted as `-` but not `_` — an arbitrary
    distinction. 47 were top-level nodes with a one-word id.
    """
    assert row(id=ident).id == ident


@pytest.mark.parametrize("ident", ["Acme.Widgets", "acme widgets", "acme..widgets", ""])
def test_malformed_ids_are_still_rejected(ident):
    """Widened is not unconstrained.

    Lowercase stays required: a case-sensitive identifier that is sometimes
    capitalised is a duplicate waiting to happen.
    """
    with pytest.raises(Exception):
        row(id=ident)


# --------------------------------------------------------------------------
# The registry itself
# --------------------------------------------------------------------------

def test_every_registered_field_is_documented():
    """A registry entry with no note is a field nobody understands."""
    for name, f in REGISTRY.items():
        assert f.kind in (VERBATIM, PROVENANCE, BATCH_LEVEL, ANNOTATION), name
        assert len(f.note) > 25, f"{name}: note too thin to be useful"


def test_aliases_point_at_a_field_that_exists():
    """An alias to a field that does not exist is worse than no alias.

    It reads as a documented relationship while pointing nowhere. A vendor
    field may alias a core field OR another vendor field —
    `vendor_category_source` records where `vendor_category` came from, and
    both are the vendor's.
    """
    known = set(Row.model_fields) | set(REGISTRY)
    for name, f in REGISTRY.items():
        if f.alias_of is not None:
            assert f.alias_of in known, f"{name}: alias_of={f.alias_of!r} names nothing"
            assert f.alias_of != name, f"{name}: aliases itself"


def test_no_registered_field_shadows_a_core_field():
    """An extension named like a core field would silently take precedence."""
    core = set(Row.model_fields)
    clashes = sorted(set(REGISTRY) & core)
    assert not clashes, f"registered vendor fields collide with core fields: {clashes}"


def test_aliases_are_discoverable_from_the_core_field():
    from kbqa.extensions import aliases_of

    mech = aliases_of("mechanism", REGISTRY)
    assert "mechanism_raw" in mech
    assert "outcome_raw" not in mech


def test_schema_version_is_enforced():
    assert row().schema_version == SCHEMA_VERSION
    with pytest.raises(Exception) as e:
        row(schema_version=2)
    assert "a version bump is a commit" in str(e.value)
