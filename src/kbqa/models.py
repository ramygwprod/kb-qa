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
"""

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 2


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
    verify = "[verify]"


class DepthLevel(str, Enum):
    product_line = "product-line"
    module = "module"
    sub_module = "sub-module"
    feature = "feature"
    sub_feature = "sub-feature"


class Row(BaseModel):
    """One vendor fact, sourced to one quote on one page.

    extra="forbid": the field set IS the contract. A collector inventing
    `confidence_note` fails immediately rather than growing the schema
    silently — which is how 91 annotation fields accumulated before.
    """

    model_config = {"extra": "forbid"}

    schema_version: int = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9]+(\.[a-z0-9\-]+)+$")
    vendor_term: str = Field(min_length=1)
    what_it_does: str = Field(min_length=1)
    source_url: str
    source_quote: str = Field(min_length=1)
    access_date: date
    evidence_grade: EvidenceGrade
    confidence: Literal["high", "medium", "low"]
    mechanism: Mechanism
    outcome: Outcome
    depth_level: DepthLevel
    canonical: str = "NOVEL"
    broken_source: bool = False
    parent_path: Optional[str] = None

    # Optional vendor-fact fields. Named in the spec; extended only by a
    # version bump, never by a collector.
    usecase_of: Optional[str] = None

    # --- v2: fields the collector emits that v1 did not name -----------------
    #
    # Typed `Optional[str]` rather than as enums on purpose. Their value sets
    # were observed in ONE batch, and an enum inferred from one sample would
    # reject legitimate values found in the next — inventing a constraint and
    # calling it a contract. `kbqa sweep --field-values` collects the real
    # distributions estate-wide; constrain them in v3 from that evidence.
    #
    # Three of these held a single value across all 222 rows of the batch they
    # were observed in, which is what an unexercised default looks like. That
    # is recorded in docs/DECISIONS.md as open, not settled here: a field that
    # never varies is a question for the collector, not a validation failure.
    node_kind: Optional[str] = None
    deployment: Optional[str] = None
    plan_gating: Optional[str] = None
    vendor_category: Optional[str] = None
    vendor_category_source: Optional[str] = None

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


# The staging frontmatter contract lives in docs/STAGING-FORMAT.md, not here.
# A Pydantic model for it existed in v1, was never referenced by any gate, and
# disagreed with both the spec and the collector's real output. G1 reads the
# frontmatter directly and reports each missing key as its own finding, which
# gives the maker a specific remedy instead of one opaque validation error.
