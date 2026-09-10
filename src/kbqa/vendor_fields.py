"""The vendor-field registry — names recorded, values never constrained.

Why this exists
---------------
Vendors differ in product structure, naming, depth and scale. Genuinely: a
vendor with six hierarchy levels and one with three are not two encodings of the
same tree. `vendor_category` holds 622 distinct values across the estate because
vendors really do use 622 categories.

§G3 already settles the principle for text — never normalise spelling, because
vendor typos are evidence. Structure is evidence by the same argument, so an
enum drawn from whichever vendors were collected first would edit the evidence
to fit our model and reject the next vendor's vocabulary as invalid.

The tension, and how it resolves
--------------------------------
`extra="forbid"` exists because 91 annotation fields once accumulated unnoticed
(§2). But a closed field set cannot record what vendors actually publish. Both
concerns are real, and they resolve by separating two different questions:

    the field NAME    must be declared here — deliberately, in a commit.
                      This is what stops silent accumulation.

    the field VALUE   is never constrained. This is what preserves the
                      vendor's own structure verbatim.

So a collector cannot invent `confidence_note` and have it pass. But once a
field is registered, whatever the vendor puts in it is recorded as-is.

Nothing here renames anything. Rows keep the exact keys the collector wrote;
`alias_of` records how a field RELATES to a core field without touching either.
Renaming would be a form of the editing this whole package exists to prevent.
"""

from typing import Dict, NamedTuple, Optional

VERBATIM = "verbatim"        # the vendor's own structure or vocabulary
PROVENANCE = "provenance"    # how we came to record something
BATCH_LEVEL = "batch-level"  # a fact about the batch, repeated on each row
ANNOTATION = "annotation"    # a one-off note; a candidate for removal


class VendorField(NamedTuple):
    kind: str
    alias_of: Optional[str]
    note: str


def _f(kind: str, alias_of: Optional[str], note: str) -> VendorField:
    return VendorField(kind, alias_of, note)


# Registered from `kbqa sweep --field-values` run against a real estate.
# Field NAMES are the collector's schema and belong here. Observed VALUES
# do not: they are one collection's vocabulary, and writing them down
# would make the tool a mirror of what it has already seen.
# See docs/DECISIONS.md D-004 (observations) and D-005 (the ruling).
REGISTRY: Dict[str, VendorField] = {
    # --- the vendor's own structure -------------------------------------
    "node_kind": _f(VERBATIM, "depth_level",
                    "The vendor's own node type, in their vocabulary. Not an "
                    "enum, and deliberately not enumerated here: listing the "
                    "values one collection happened to use would anchor them as "
                    "canonical, and the next vendor's vocabulary would read as "
                    "wrong rather than different."),
    "deployment": _f(VERBATIM, None,
                     "How the vendor says the thing is deployed, in their "
                     "words. Some values are short and enum-like, others are "
                     "elaborations — a vendor being specific, not a malformed "
                     "enum value."),
    "plan_gating": _f(VERBATIM, None,
                      "Which plan or tier gates the feature, in the vendor's "
                      "words. 133 distinct."),
    "vendor_category": _f(VERBATIM, "canonical",
                          "The vendor's own category for this node. High "
                          "cardinality by nature — their taxonomy, not ours."),
    "product_line": _f(VERBATIM, None, "The vendor's product line name."),
    "pillar": _f(VERBATIM, None, "The vendor's top-level grouping."),
    "parent": _f(VERBATIM, "parent_path",
                 "Parent node id in the vendor's own tree."),
    "children_count": _f(VERBATIM, None, "Children the vendor lists under this node."),
    "tagline_for": _f(VERBATIM, None, "What the vendor's tagline is attached to."),
    "third_party": _f(VERBATIM, None, "Third party the vendor names."),
    "mechanism_third_party": _f(VERBATIM, "mechanism",
                                "Third party the vendor credits for the mechanism."),
    "cloud_provider": _f(VERBATIM, None, "Cloud provider and region, as printed."),
    "hosting_location": _f(VERBATIM, None, "Hosting location, as printed."),
    "region": _f(VERBATIM, None, "Region identifiers, as printed."),
    "regulator": _f(VERBATIM, None, "Regulator named by the vendor."),
    "version": _f(VERBATIM, None, "Version or minimum-platform string, as printed."),
    "limit": _f(VERBATIM, None,
                "A stated limit, in the vendor's words. Observed holding a full "
                "sentence — prose in a key. Kept because it is the vendor's "
                "text; flagged in D-005 as possibly not a field at all."),
    "locale_scope": _f(VERBATIM, None,
                       "Locale coverage note. Also observed holding a sentence."),
    "language_count_observed": _f(VERBATIM, None, "Languages counted on the page."),
    "undisclosed_amount": _f(VERBATIM, None, "Vendor declined to state an amount."),

    # --- how we came to record it ---------------------------------------
    "mechanism_raw": _f(PROVENANCE, "mechanism",
                        "The vendor's exact wording before normalisation. This "
                        "is verbatim preservation working: our `mechanism` enum "
                        "stays recoverable back to what was actually said."),
    "mechanism_reported": _f(PROVENANCE, "mechanism", "As reported by the vendor."),
    "mechanism_via": _f(PROVENANCE, "mechanism",
                        "The route by which the mechanism is provided."),
    "outcome_raw": _f(PROVENANCE, "outcome",
                      "The vendor's exact wording before normalisation."),
    "outcome_reported": _f(PROVENANCE, "outcome", "As reported by the vendor."),
    "prior_tree_mechanism": _f(PROVENANCE, "mechanism",
                               "What a previous collection round recorded."),
    "vendor_category_source": _f(PROVENANCE, "vendor_category",
                                 "Where the category was read from — a "
                                 "breadcrumb, a nav element, the URL path, the "
                                 "vendor's own classification. A claim about "
                                 "our method, not about the vendor."),
    "children_enumerated": _f(PROVENANCE, None,
                              "Whether children were actually enumerated or "
                              "only counted. A claim about our own coverage."),
    "page_modified": _f(PROVENANCE, None, "Last-modified date printed on the page."),
    "page_modified_time": _f(PROVENANCE, None, "Last-modified timestamp, as printed."),
    "product_page": _f(PROVENANCE, "source_url", "The vendor's product page for this node."),
    "real_href": _f(PROVENANCE, "source_url", "The href behind a link, where it differs."),

    # --- batch-level facts repeated per row ------------------------------
    # Harmless redundancy, but they belong in frontmatter. D-005 leaves the
    # move open; registering them stops them failing rows in the meantime.
    "vendor": _f(BATCH_LEVEL, None, "Vendor name. Also in frontmatter."),
    "batch": _f(BATCH_LEVEL, None, "Batch name. Also in frontmatter."),
    "id_prefix": _f(BATCH_LEVEL, None, "Common prefix of every id in the batch."),
    "round": _f(BATCH_LEVEL, None,
                "Which collection round produced the batch. Observed at a "
                "single value, so it may be an unexercised default."),
    "node_count": _f(BATCH_LEVEL, None,
                     "How many nodes the batch contains. A claim about the "
                     "batch, repeated on every row of it."),
    # --- collection-time notes -------------------------------------------
    # Registered as ANNOTATION deliberately: each records something real that
    # was observed while collecting, but NINE separate note fields for what is
    # essentially "something was odd here" is the §2 accumulation pattern in
    # miniature. They pass validation and stay visible as candidates for
    # consolidation into one structured field.
    "duplicate_note": _f(ANNOTATION, None,
                         "A note that this node appears more than once. 61 rows."),
    "id_collision_with": _f(ANNOTATION, "id",
                            "Another node id this one collides with. A real "
                            "structural fact, worth keeping in some form."),
    "contradiction": _f(ANNOTATION, None,
                        "The vendor contradicts itself, or contradicts another page."),
    "contradiction_note": _f(ANNOTATION, None,
                             "Free-text detail on a contradiction. Overlaps "
                             "`contradiction`; the two should probably be one field."),
    "source_typo": _f(ANNOTATION, "source_quote",
                      "The vendor's page contains a typo. Recorded rather than "
                      "corrected — §G3 treats typos as evidence."),
    "mechanism_correction": _f(ANNOTATION, "mechanism",
                               "A correction applied to a previously recorded mechanism."),
    "scope_qualifier": _f(ANNOTATION, None,
                          "Narrows what the row's claim applies to."),
    "taxonomy_source": _f(ANNOTATION, "vendor_category",
                          "Where a taxonomy decision came from. Overlaps "
                          "`vendor_category_source`."),
    "nodes": _f(ANNOTATION, None,
                "Observed twice. Purpose unclear from shape alone — a candidate "
                "for removal unless the collector can say what it means."),
}



def is_registered(name: str) -> bool:
    return name in REGISTRY


def aliases_of(core_field: str) -> Dict[str, VendorField]:
    """Every registered field that relates to a given core field."""
    return {n: f for n, f in REGISTRY.items() if f.alias_of == core_field}


def by_kind(kind: str) -> Dict[str, VendorField]:
    return {n: f for n, f in REGISTRY.items() if f.kind == kind}
