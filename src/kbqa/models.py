"""The contract as code. A row either validates or raises.

Changing this file is a version bump, a commit, and a recorded decision.
Never mid-run. (spec §2)

Schema history
--------------
v1  Written from the specification alone, before any real row was seen.
v2  Reconciled with the estate (2026-09-08). Five fields the collector has
    always emitted were absent from v1, so every real row failed conformance
    on fields that were never in dispute. See docs/DECISIONS.md for the
    evidence and the reasoning per field.

    `extra="forbid"` is unchanged and still load-bearing: naming five known
    fields does not open the door to a sixth. The guarantee is that the field
    set is decided here, deliberately, and not grown by a collector at runtime.

v3  Split the contract by owner (2026-09-09), after the estate showed a strict
    flat field set cannot record what vendors actually publish. Vendors differ
    in structure, naming, depth and scale, and §G3's rule for text — never
    normalise spelling, vendor typos are evidence — applies to structure too.

    core            ours. Strict, enum-validated. Provenance and grounding.
    vendor fields   theirs. The NAME must be registered in vendor_fields.py,
                    deliberately, in a commit — that is what stops silent
                    accumulation. The VALUE is never constrained — that is
                    what preserves the vendor's structure verbatim.

    Nothing is renamed. Rows keep the exact keys the collector wrote;
    `alias_of` in the registry records how a field relates to a core field
    without touching either. Renaming would be a form of the editing this
    package exists to prevent.
"""

from datetime import date
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from .vendor_fields import is_registered  # noqa: E402

SCHEMA_VERSION = 3


class Mechanism(str, Enum):
    native = "Native"
    composed = "Composed"
    integrated = "Integrated"
    byo = "BYO"
    none = "None"
    unknown = "unknown"


class Outcome(str, Enum):
    yes = "yes"
    partial = "partial"
    no = "no"
    na = "na"
    unknown = "unknown"


class EvidenceGrade(str, Enum):
    official_doc = "official-doc"
    help = "help"
    marketing = "marketing"
    verified = "verified"
    # Both spellings are accepted. The spec writes `[verify]`; the collector
    # writes `verify`. This is OUR field and OUR enum, so the mismatch was a
    # real defect rather than vendor structure — but rejecting rows over a pair
    # of brackets taught nothing, so both forms are recorded as written.
    verify = "verify"
    verify_bracketed = "[verify]"


class DepthLevel(str, Enum):
    product_line = "product-line"
    module = "module"
    sub_module = "sub-module"
    feature = "feature"
    sub_feature = "sub-feature"


class Row(BaseModel):
    """One vendor fact, sourced to one quote on one page.

    The field set is still the contract, but it has two halves with different
    owners (v3, see docs/DECISIONS.md D-005):

    **Core** — declared below, strict, enum-validated. Provenance and grounding:
    the fields that make a claim checkable. A collector inventing
    `confidence_note` still fails on the first row.

    **Vendor fields** — anything registered in `vendor_fields.py`. The NAME must
    be there, added deliberately in a commit, which is what stops the silent
    accumulation §2 describes. The VALUE is never constrained, which is what
    preserves the vendor's own structure verbatim.

    An unregistered field is a violation. That is the line `extra="forbid"` used
    to draw, drawn now in the one place that does not also reject vendors for
    having their own vocabulary.
    """

    model_config = {"extra": "allow"}

    schema_version: int = SCHEMA_VERSION
    # Lowercase dotted path. Underscores are allowed and a single segment is
    # valid — both were rejected by v1's pattern, which cost 904 rows across the
    # estate: 857 for containing `_` (permitted `-` but not `_`, an arbitrary
    # distinction) and 47 for being top-level nodes with a one-word id.
    #
    # Lowercase stays required. Not because the data would otherwise break the
    # rule — no id in the estate uses uppercase — but because a case-sensitive
    # identifier that is sometimes capitalised is a duplicate waiting to happen.
    id: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_\-]+)*$")
    vendor_term: str = Field(min_length=1)
    what_it_does: str = Field(min_length=1)
    source_url: str
    source_quote: str = Field(min_length=1)
    access_date: date
    evidence_grade: EvidenceGrade
    confidence: Literal["high", "medium", "low"]
    mechanism: Mechanism
    outcome: Outcome

    # Accepts the named levels OR the vendor's own numeric depth.
    #
    # Some vendors' hierarchies do not fit five names. A numeric depth records a
    # node's position in THAT vendor's tree; the names impose ours. Forcing one
    # convention would flatten a real structural difference into a false one —
    # the same error as normalising a vendor's spelling.
    depth_level: Union[str, int]

    canonical: str = "NOVEL"
    broken_source: bool = False
    parent_path: Optional[str] = None
    usecase_of: Optional[str] = None

    @field_validator("depth_level", mode="before")
    @classmethod
    def named_or_numeric_depth(cls, v):
        """Accepts `4` and `"4"` alike.

        The collector writes numeric depth as a JSON integer. Declaring the
        field `str` rejected 170 rows on type before this validator ever ran —
        making numeric depth work only if it happened to be quoted, which is a
        distinction the data does not draw.
        """
        s = str(v).strip()
        if s in {d.value for d in DepthLevel} or s.isdigit():
            return s
        raise ValueError(
            f"depth_level {v!r} is neither a named level "
            f"({', '.join(d.value for d in DepthLevel)}) nor a numeric depth"
        )

    @field_validator("source_url")
    @classmethod
    def real_source(cls, v: str) -> str:
        if not (v.startswith(("http://", "https://")) or v.startswith("doc:")):
            raise ValueError("source_url must be a fetched URL or a doc: reference")
        return v

    @field_validator("schema_version")
    @classmethod
    def known_schema(cls, v: int) -> int:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version {v} != {SCHEMA_VERSION}; "
                "a version bump is a commit, not a runtime accommodation"
            )
        return v

    @model_validator(mode="after")
    def extras_must_be_registered(self):
        """Every non-core field must be a registered vendor field.

        This is where `extra="forbid"` moved to. It still refuses a field nobody
        declared — but it refuses the NAME, not the value, so a vendor's own
        vocabulary passes while an invented annotation does not.
        """
        extras = self.__pydantic_extra__ or {}
        unregistered = sorted(k for k in extras if not is_registered(k))
        if unregistered:
            raise ValueError(
                "unregistered field(s): " + ", ".join(unregistered)
                + ". Register in src/kbqa/vendor_fields.py with a note on what "
                "the vendor means by it, or stop emitting it. A field nobody "
                "declared is how 91 annotations accumulated."
            )
        return self


# The staging frontmatter contract lives in docs/STAGING-FORMAT.md, not here.
# A Pydantic model for it existed in v1, was never referenced by any gate, and
# disagreed with both the spec and the collector's real output. G1 reads the
# frontmatter directly and reports each missing key as its own finding, which
# gives the maker a specific remedy instead of one opaque validation error.
