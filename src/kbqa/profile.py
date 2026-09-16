"""Profiles — the analytical framework, separated from the grounding machinery.

Three layers, and they answer to different owners. This is D-005's split taken
one step further out:

    universal   ours, and everyone's. `id`, `source_url`, `source_quote`,
                `access_date`, `evidence_grade`, `confidence`. These are what
                make ANY claim checkable, in any domain. A gate that verifies a
                quote appears on the page it cites does not care whether the
                subject is a software vendor, a hiring market or a regulator.

    profile     one programme's analytical framework. `mechanism`,
                `outcome`, `depth_level` express a specific way of analysing
                competitive features. A programme studying pricing posture or
                compliance would keep every universal field and replace all of
                these.

    extensions  the subject's own vocabulary. Names registered, values never
                constrained. (docs/DECISIONS.md D-005)

Why this matters beyond tidiness: a tool whose core hardcodes one framework
quietly asserts that framework is how the world is. Collecting intelligence in
a new sector would then mean either distorting it into `Native / Composed /
Integrated / BYO`, or forking the gates. Both are ways of letting what was
collected first decide what can be collected next.

The gates never see a profile. They work against parsed structures and a row
model, so swapping the framework changes no gate logic.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Type

from pydantic import BaseModel

from .conventions import DEFAULT as DEFAULT_CONVENTIONS
from .conventions import Conventions
from .extensions import ExtensionField


@dataclass(frozen=True)
class Profile:
    """One collection programme's framework, conventions and extension registry."""

    name: str
    description: str
    row_model: Type[BaseModel]
    extensions: Dict[str, ExtensionField] = field(default_factory=dict)
    conventions: Conventions = DEFAULT_CONVENTIONS

    #: Fields that are the SUBJECT's own words, never ours to change.
    #:
    #: The universal four are always verbatim: an id someone else may cite, the
    #: page a claim came from, the quote itself, and when it was read. A profile
    #: adds whatever else in its framework belongs to the subject rather than to
    #: us — for a product catalogue, the vendor's term for a thing and where the
    #: vendor puts it in their own tree.
    #:
    #: Everything NOT listed here is ours to revise: our grading, our
    #: confidence, our mapping. That is the whole distinction the alias layer
    #: rests on, and `kbqa freeze` is what turns it from a promise into a check.
    verbatim_fields: Tuple[str, ...] = (
        "id", "source_url", "source_quote", "access_date",
    )

    def is_registered(self, field_name: str) -> bool:
        return field_name in self.extensions


_REGISTRY: Dict[str, Profile] = {}
_ACTIVE: Optional[str] = None


def register(profile: Profile) -> Profile:
    if profile.name in _REGISTRY:
        raise ValueError(f"profile {profile.name!r} is already registered")
    _REGISTRY[profile.name] = profile
    return profile


def available() -> Dict[str, Profile]:
    return dict(_REGISTRY)


def activate(name: str) -> Profile:
    """Select the profile every gate validates against.

    Deliberately explicit and global rather than passed through every call:
    running two profiles against one corpus in a single process would produce
    verdicts whose contract is ambiguous, and a verdict whose contract is
    unclear is worse than no verdict.
    """
    global _ACTIVE
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown profile {name!r}; available: {', '.join(sorted(_REGISTRY)) or 'none'}"
        )
    _ACTIVE = name
    return _REGISTRY[name]


def active() -> Profile:
    if _ACTIVE is None:
        raise RuntimeError(
            "no profile is active. A profile names the analytical framework a "
            "row is validated against; without one there is no contract to "
            "check against and a PASS would mean nothing."
        )
    return _REGISTRY[_ACTIVE]


def row_model() -> Type[BaseModel]:
    return active().row_model


def conventions() -> Conventions:
    return active().conventions


def extensions() -> Dict[str, ExtensionField]:
    return active().extensions
