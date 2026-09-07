"""The contract as code. A row either validates or raises.

Changing this file is a version bump, a commit, and a note in
_DECISIONS-OPEN.md. Never mid-run. (spec §2)
"""

from datetime import date
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 1


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


class StagingFrontmatter(BaseModel):
    """Frontmatter of a _collect-<batch>-staging.md file.

    `fetched_by_this_agent` is an attestation. G6 FAILs on true — attestation
    is not proof of role separation, but a true value is proof of its
    collapse. (spec §G6)
    """

    model_config = {"extra": "allow"}

    batch: str = Field(min_length=1)
    vendor: str = Field(min_length=1)
    source_capture: str = Field(min_length=1)
    source_capture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: List[str] = Field(min_length=1)
    fetched_by_this_agent: bool = False
