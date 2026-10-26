"""Profile: vendor catalogue — competitive feature analysis.

One analytical framework among many. It expresses features as a mechanism
(how the capability is provided) and an outcome (whether it is supported),
positioned at a depth in the subject's own hierarchy.

A programme studying something else — pricing posture, compliance, hiring —
keeps every universal field in `models.CoreRow` and replaces everything here.
That is the point of the split: the grounding machinery does not care what is
being analysed, only that each claim is traceable to a quote on a page.

⚠ Values observed while collecting are deliberately NOT written down here.
Recording one collection's vocabulary would make the tool a mirror of what it
has already seen, and the next subject's vocabulary would read as wrong rather
than different.
"""

from enum import Enum
from typing import Dict, List, Literal, Optional, Tuple, Union, get_args

from pydantic import Field, field_validator

from ..conventions import DEFAULT as DEFAULT_CONVENTIONS
from ..extensions import (ANNOTATION, BATCH_LEVEL, PROVENANCE, VERBATIM,
                          ExtensionField, ext)
from ..models import CoreRow
from ..profile import Profile, register


class EvidenceGrade(str, Enum):
    """How authoritative the source is, in THIS programme's vocabulary.

    Every domain grades its sources; the grades differ. A programme reading
    regulatory filings or peer-reviewed work would replace all of these, and a
    core that fixed them would make its own first corpus the standard.
    """
    official_doc = "official-doc"
    help = "help"
    marketing = "marketing"
    verified = "verified"
    # Both spellings accepted. The specification writes `[verify]`; collectors
    # write `verify`. Rejecting rows over a pair of brackets taught nothing.
    verify = "verify"
    verify_bracketed = "[verify]"


class Mechanism(str, Enum):
    """How a capability is provided. This framework's axis, not a universal."""
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


class DepthLevel(str, Enum):
    """Named levels. Subjects whose hierarchy does not fit five names record a
    numeric depth instead; both are accepted."""
    product_line = "product-line"
    module = "module"
    sub_module = "sub-module"
    feature = "feature"
    sub_feature = "sub-feature"


# Every feature has a position in its subject's hierarchy, so `unknown` means
# the page does not show it — never that nobody looked. A page that shows a
# breadcrumb gives a depth by counting it; `strict_row_check` refuses `unknown`
# there. (PIPELINE-SPEC §3: `unknown` when the page is silent.)
DEPTH_UNKNOWN = "unknown"


class Row(CoreRow):
    """A universal grounded claim, plus this framework's analytical fields."""

    evidence_grade: EvidenceGrade
    confidence: Literal["high", "medium", "low"]
    vendor_term: str = Field(min_length=1)
    what_it_does: str = Field(min_length=1)
    mechanism: Mechanism
    outcome: Outcome
    depth_level: Union[str, int]
    canonical: str = "NOVEL"
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
        if s in {d.value for d in DepthLevel} or s.isdigit() or s == DEPTH_UNKNOWN:
            return s
        raise ValueError(
            f"depth_level {v!r} is neither a named level "
            f"({', '.join(d.value for d in DepthLevel)}), a numeric depth, "
            f"nor `{DEPTH_UNKNOWN}`"
        )


# Registered from `kbqa sweep --field-values` run against a real estate.
# Field NAMES are the collector's schema and belong here. Observed VALUES
# do not: they are one collection's vocabulary, and writing them down
# would make the tool a mirror of what it has already seen.
# See docs/DECISIONS.md D-004 (observations) and D-005 (the ruling).
EXTENSIONS: Dict[str, ExtensionField] = {
    # --- the subject's own structure -------------------------------------
    "node_kind": ext(VERBATIM, "depth_level",
                    "The subject's own node type, in their vocabulary. Not an "
                    "enum, and deliberately not enumerated here: listing the "
                    "values one collection happened to use would anchor them as "
                    "canonical, and the next subject's vocabulary would read as "
                    "wrong rather than different."),
    "deployment": ext(VERBATIM, None,
                     "How the subject says the thing is deployed, in their "
                     "words. Some values are short and enum-like, others are "
                     "elaborations — a vendor being specific, not a malformed "
                     "enum value."),
    "plan_gating": ext(VERBATIM, None,
                      "Which plan or tier gates the feature, in the subject's "
                      "words. 133 distinct."),
    "vendor_category": ext(VERBATIM, "canonical",
                          "The subject's own category for this node. High "
                          "cardinality by nature — their taxonomy, not ours."),
    "product_line": ext(VERBATIM, None, "The subject's product line name."),
    "pillar": ext(VERBATIM, None, "The subject's top-level grouping."),
    "parent": ext(VERBATIM, "parent_path",
                 "Parent node id in the subject's own tree."),
    "children_count": ext(VERBATIM, None, "Children the subject lists under this node."),
    "tagline_for": ext(VERBATIM, None, "What the subject's tagline is attached to."),
    "third_party": ext(VERBATIM, None, "Third party the subject names."),
    "mechanism_third_party": ext(VERBATIM, "mechanism",
                                "Third party the subject credits for the mechanism."),
    "cloud_provider": ext(VERBATIM, None, "Cloud provider and region, as printed."),
    "hosting_location": ext(VERBATIM, None, "Hosting location, as printed."),
    "region": ext(VERBATIM, None, "Region identifiers, as printed."),
    "regulator": ext(VERBATIM, None, "Regulator named by the vendor."),
    "version": ext(VERBATIM, None, "Version or minimum-platform string, as printed."),
    "limit": ext(VERBATIM, None,
                "A stated limit, in the subject's words. Observed holding a full "
                "sentence — prose in a key. Kept because it is the subject's "
                "text; flagged in D-005 as possibly not a field at all."),
    "locale_scope": ext(VERBATIM, None,
                       "Locale coverage note. Also observed holding a sentence."),
    "language_count_observed": ext(VERBATIM, None, "Languages counted on the page."),
    "undisclosed_amount": ext(VERBATIM, None, "Vendor declined to state an amount."),

    # --- how we came to record it ---------------------------------------
    "mechanism_raw": ext(PROVENANCE, "mechanism",
                        "The subject's exact wording before normalisation. This "
                        "is verbatim preservation working: our `mechanism` enum "
                        "stays recoverable back to what was actually said."),
    "mechanism_reported": ext(PROVENANCE, "mechanism", "As reported by the vendor."),
    "mechanism_via": ext(PROVENANCE, "mechanism",
                        "The route by which the mechanism is provided."),
    "outcome_raw": ext(PROVENANCE, "outcome",
                      "The subject's exact wording before normalisation."),
    "outcome_reported": ext(PROVENANCE, "outcome", "As reported by the vendor."),
    "prior_tree_mechanism": ext(PROVENANCE, "mechanism",
                               "What a previous collection round recorded."),
    "vendor_category_source": ext(PROVENANCE, "vendor_category",
                                 "Where the category was read from — a "
                                 "breadcrumb, a nav element, the URL path, the "
                                 "subject's own classification. A claim about "
                                 "our method, not about the vendor."),
    "children_enumerated": ext(PROVENANCE, None,
                              "Whether children were actually enumerated or "
                              "only counted. A claim about our own coverage."),
    "page_modified": ext(PROVENANCE, None, "Last-modified date printed on the page."),
    "page_modified_time": ext(PROVENANCE, None, "Last-modified timestamp, as printed."),
    "product_page": ext(PROVENANCE, "source_url", "The subject's product page for this node."),
    "real_href": ext(PROVENANCE, "source_url", "The href behind a link, where it differs."),

    # --- the way in, and the one feature behind several ways in -----------
    # An interface (API operation, SDK method, webhook, CLI command, settings
    # screen) is how a feature is reached or set up, never a feature itself
    # (the operator's ruling, 2026-10-18). Its record is a row like any other —
    # grounded by its own quote — that names the way in; the feature behind it
    # is the row `same_feature_as` points to, classified once. Standard terms:
    # ArchiMate's application interface / application service; OpenAPI's
    # operation and parameter.
    "same_feature_as": ext(PROVENANCE, "id",
                          "This row is another source of the feature whose row "
                          "id it names (the anchor, which carries no "
                          "`same_feature_as` itself). Kept and grounded — its "
                          "words, its URL and any role it names stay — and not "
                          "classified: it takes the anchor's classification."),
    "interface_type": ext(PROVENANCE, None,
                         "The way in this row documents: `API`, `SDK`, "
                         "`webhook`, `CLI` or `user interface`."),
    "operation": ext(VERBATIM, None,
                    "The operation, method, command or screen, as printed."),
    "parameter": ext(VERBATIM, None,
                    "The setting or field inside the operation that delivers "
                    "this row's function, as printed."),

    # --- batch-level facts repeated per row ------------------------------
    # Harmless redundancy, but they belong in frontmatter. D-005 leaves the
    # move open; registering them stops them failing rows in the meantime.
    "vendor": ext(BATCH_LEVEL, None, "Vendor name. Also in frontmatter."),
    "batch": ext(BATCH_LEVEL, None, "Batch name. Also in frontmatter."),
    "id_prefix": ext(BATCH_LEVEL, None, "Common prefix of every id in the batch."),
    "round": ext(BATCH_LEVEL, None,
                "Which collection round produced the batch. Observed at a "
                "single value, so it may be an unexercised default."),
    "node_count": ext(BATCH_LEVEL, None,
                     "How many nodes the batch contains. A claim about the "
                     "batch, repeated on every row of it."),
    # --- collection-time notes -------------------------------------------
    # Registered as ANNOTATION deliberately: each records something real that
    # was observed while collecting, but NINE separate note fields for what is
    # essentially "something was odd here" is the §2 accumulation pattern in
    # miniature. They pass validation and stay visible as candidates for
    # consolidation into one structured field.
    "duplicate_note": ext(ANNOTATION, None,
                         "A note that this node appears more than once. 61 rows."),
    "id_collision_with": ext(ANNOTATION, "id",
                            "Another node id this one collides with. A real "
                            "structural fact, worth keeping in some form."),
    "contradiction": ext(ANNOTATION, None,
                        "The vendor contradicts itself, or contradicts another page."),
    "contradiction_note": ext(ANNOTATION, None,
                             "Free-text detail on a contradiction. Overlaps "
                             "`contradiction`; the two should probably be one field."),
    "source_typo": ext(ANNOTATION, "source_quote",
                      "The subject's page contains a typo. Recorded rather than "
                      "corrected — §G3 treats typos as evidence."),
    "mechanism_correction": ext(ANNOTATION, "mechanism",
                               "A correction applied to a previously recorded mechanism."),
    "scope_qualifier": ext(ANNOTATION, None,
                          "Narrows what the row's claim applies to."),
    "taxonomy_source": ext(ANNOTATION, "vendor_category",
                          "Where a taxonomy decision came from. Overlaps "
                          "`vendor_category_source`."),
    "nodes": ext(ANNOTATION, None,
                "Observed twice. Purpose unclear from shape alone — a candidate "
                "for removal unless the collector can say what it means."),
}

# The ways in a row may name in `interface_type` — standard terms, one spelling each.
INTERFACE_TYPES = ("API", "SDK", "webhook", "CLI", "user interface")
# The fields that say which part of an interface a row documents.
INTERFACE_DETAIL = "operation parameter".split()

# The schema's spelling of each grade — one spelling per value (K1). The enum
# above still accepts both spellings of "verify", because legacy rows use the
# bare form and are never edited. A NEW batch writes the schema's spelling.
SCHEMA_EVIDENCE_GRADES = ("official-doc", "help", "marketing", "verified", "[verify]")
# The bare spelling of a grade whose schema spelling is bracketed.
BARE_EVIDENCE_GRADES = {"verify": "[verify]"}


def schema_evidence_grade(value: object) -> Optional[str]:
    """The schema's spelling of a grade written another known way — in another
    case, with spaces, or bare (`verify` for `[verify]`) — else None. A value
    that is no known respelling of one grade is never mapped to the nearest
    one: which grade was meant is the row-writer's judgement, not code's."""
    if not isinstance(value, str):
        return None
    key = "".join(value.split()).lower()
    known = {g.lower(): g for g in SCHEMA_EVIDENCE_GRADES}
    known.update(BARE_EVIDENCE_GRADES)
    return known.get(key)


def strict_row_check(obj: dict) -> List[Tuple[str, str]]:
    """K1 rules for batches collected under the current convention.

    Each returns a code the report routes as `fixable`: the row disagrees with
    the schema, and the row-writer can correct it from the capture. None of
    them is applied to legacy batches — see `Profile.strict_row_check`.
    """
    out: List[Tuple[str, str]] = []
    keys = list(obj)
    if not keys or keys[0] != "id":
        out.append((
            "id_not_first_key",
            f"first key is {keys[0] if keys else None!r}; `id` must be the first "
            "key so a line-based count sees the row",
        ))
    pp = obj.get("parent_path")
    if not isinstance(pp, str) or not pp.strip():
        out.append((
            "parent_path_empty",
            f"parent_path is {pp!r}; write the page's own breadcrumb verbatim, "
            "or `unknown` when the page shows none — never empty",
        ))
    if (str(obj.get("depth_level", "")).strip() == DEPTH_UNKNOWN
            and isinstance(pp, str) and pp.strip() and pp.strip() != "unknown"):
        out.append((
            "depth_unknown_with_breadcrumb",
            f"depth_level is `unknown` but the page shows the breadcrumb {pp!r}; "
            "count its levels for a numeric depth, or use the level the page states",
        ))
    itype = obj.get("interface_type")
    if itype is not None and itype not in INTERFACE_TYPES:
        out.append((
            "interface_type_unknown",
            f"interface_type {itype!r} is not one of {' | '.join(INTERFACE_TYPES)}",
        ))
    if itype is None and any(obj.get(k) not in (None, "") for k in INTERFACE_DETAIL):
        out.append((
            "interface_without_type",
            "the row names an `operation` or `parameter` but no `interface_type`: say "
            "which way in it documents",
        ))
    sfa = obj.get("same_feature_as")
    if sfa is not None and (not isinstance(sfa, str) or not sfa.strip() or sfa == obj.get("id")):
        out.append((
            "same_feature_as_invalid",
            f"same_feature_as is {sfa!r}; it names the row id of another row of the same "
            "feature (its anchor), never empty and never the row's own id",
        ))
    grade = obj.get("evidence_grade")
    if grade not in SCHEMA_EVIDENCE_GRADES:
        out.append((
            "evidence_grade_spelling",
            f"evidence_grade {grade!r} is not one of the schema's spellings "
            f"({' | '.join(SCHEMA_EVIDENCE_GRADES)})",
        ))
    return out


PROFILE = register(Profile(
    name="vendor-catalogue",
    description=(
        "Competitive feature analysis: capabilities expressed as a mechanism "
        "and an outcome, positioned in the subject's own hierarchy."
    ),
    row_model=Row,
    extensions=EXTENSIONS,
    conventions=DEFAULT_CONVENTIONS,
    # The subject's own naming and their own nesting. `vendor_term` is what
    # they call the thing; `parent_path` is where they put it. Both are
    # evidence of how the subject organises itself, which is the difference
    # this programme exists to preserve — so neither is ours to tidy while
    # mapping. Everything else in the framework (grading, confidence,
    # mechanism, outcome, canonical) is our reading and stays revisable.
    verbatim_fields=(
        "id", "source_url", "source_quote", "access_date",
        "vendor_term", "parent_path",
    ),
    strict_row_check=strict_row_check,
    # What `kbqa stage` holds a draft's judgement to before the check: the
    # schema's spelling of each value (one spelling per value, K1).
    enumerated={
        "evidence_grade": SCHEMA_EVIDENCE_GRADES,
        "confidence": get_args(Row.model_fields["confidence"].annotation),
        "mechanism": tuple(m.value for m in Mechanism),
        "outcome": tuple(o.value for o in Outcome),
        "interface_type": INTERFACE_TYPES,
    },
    respellings={"evidence_grade": schema_evidence_grade},
))
