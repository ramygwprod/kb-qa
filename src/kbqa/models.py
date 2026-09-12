"""The universal core — what makes any claim checkable, in any domain.

Changing this file is a version bump, a commit, and a recorded decision.
Never mid-run. (spec §2)

Schema history
--------------
v1  Written from the specification alone, before any real row was seen.
v2  Reconciled with a real corpus. Five fields the collector had always emitted
    were absent, so every real row failed conformance on fields that were never
    in dispute.
v3  Split by owner: core strict, subject fields verbatim. `extra="forbid"`
    moved rather than went away.
v4  Split by DOMAIN. This file now holds only what is universal to
    evidence-grounded collection; the analytical framework moved into a
    profile (`kbqa.profiles.*`).

Why v4
------
`mechanism`, `outcome` and `depth_level` express one way of analysing
competitive features. Hardcoding them here asserted that framework is how the
world is — so collecting intelligence in another sector would have meant either
distorting it into those axes or forking the gates. Both let what was collected
first decide what can be collected next.

What stays here is domain-neutral by test: a gate verifying that a quote
appears on the page it cites does not care whether the subject is a software
vendor, a labour market or a regulator.

    id              addresses one claim
    source_url      where it came from
    source_quote    the verbatim evidence
    access_date     when it was seen
    broken_source   whether the source still resolves

Anything that depends on WHAT is being studied belongs in a profile — including
`evidence_grade` and `confidence`. Every domain grades its sources, but
`official-doc / help / marketing` is one programme's vocabulary; a programme
reading regulatory filings or peer-reviewed work grades differently, and a core
that fixed those values would make its own first corpus the standard.
"""

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = 5


class CoreRow(BaseModel):
    """One grounded claim. Profiles extend this; gates validate against it.

    `extra="allow"` with a registry check: the field NAME must be declared in
    the active profile's extension registry, deliberately, in a commit — that
    is what stops silent accumulation. The VALUE is never constrained — that is
    what preserves the subject's own structure verbatim. (D-005)
    """

    model_config = {"extra": "allow"}

    schema_version: int = SCHEMA_VERSION

    # Lowercase dotted path. Underscores allowed, single segment valid — an
    # earlier pattern permitted `-` but not `_` and required two segments,
    # which together rejected 904 real rows over arbitrary distinctions.
    #
    # Lowercase stays required. Not because the data would otherwise break the
    # rule, but because a case-sensitive identifier that is sometimes
    # capitalised is a duplicate waiting to happen.
    id: str
    source_url: str
    source_quote: str = Field(min_length=1)
    access_date: date
    broken_source: bool = False

    @field_validator("id")
    @classmethod
    def id_matches_convention(cls, v: str) -> str:
        import re
        from . import profile
        pattern = profile.conventions().id_pattern
        if not re.match(pattern, v):
            raise ValueError(f"id {v!r} does not match this profile's id pattern {pattern}")
        return v

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
        """Every non-core field must be registered in the active profile.

        This is where `extra="forbid"` moved to. It still refuses a field nobody
        declared — but it refuses the NAME, not the value, so a subject's own
        vocabulary passes while an invented annotation does not.
        """
        from . import profile  # local: profiles import this module

        extras = self.__pydantic_extra__ or {}
        if not extras:
            return self

        registry = profile.active().extensions
        unregistered = sorted(k for k in extras if k not in registry)
        if unregistered:
            raise ValueError(
                "unregistered field(s): " + ", ".join(unregistered)
                + f". Register in the '{profile.active().name}' profile with a "
                "note on what the subject means by it, or stop emitting it. A "
                "field nobody declared is how annotation fields accumulate."
            )
        return self
