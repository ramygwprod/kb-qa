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
from typing import Dict, Literal, Optional, Union

from pydantic import Field, field_validator

from ..conventions import DEFAULT as DEFAULT_CONVENTIONS
from ..extensions import (ANNOTATION, BATCH_LEVEL, PROVENANCE, VERBATIM,
                          ExtensionField, ext)
from ..models import CoreRow
from ..profile import Profile, register


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


class Row(CoreRow):
    """A universal grounded claim, plus this framework's analytical fields."""

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
        if s in {d.value for d in DepthLevel} or s.isdigit():
            return s
        raise ValueError(
            f"depth_level {v!r} is neither a named level "
            f"({', '.join(d.value for d in DepthLevel)}) nor a numeric depth"
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

PROFILE = register(Profile(
    name="vendor-catalogue",
    description=(
        "Competitive feature analysis: capabilities expressed as a mechanism "
        "and an outcome, positioned in the subject's own hierarchy."
    ),
    row_model=Row,
    extensions=EXTENSIONS,
    conventions=DEFAULT_CONVENTIONS,
))
