"""Extension fields — names recorded, values never constrained.

Why this exists
---------------
Subjects differ in structure, naming, depth and scale — genuinely. Two
organisations with six and three hierarchy levels are not two encodings of the
same tree, and a field holding hundreds of distinct values usually means the
subjects really do use hundreds of categories.

§G3 already settles the principle for text — never normalise spelling, because
a subject's typos are evidence. Structure is evidence by the same argument, so
an enum drawn from whichever subjects were collected first would edit the
evidence to fit our model and reject the next one's vocabulary as invalid.

The tension, and how it resolves
--------------------------------
`extra="forbid"` exists because 91 annotation fields once accumulated unnoticed
(§2). But a closed field set cannot record what vendors actually publish. Both
concerns are real, and they resolve by separating two different questions:

    the field NAME    must be declared here — deliberately, in a commit.
                      This is what stops silent accumulation.

    the field VALUE   is never constrained. This is what preserves the
                      vendor's own structure verbatim.

So a collector cannot invent a field and have it pass. But once a field is
registered, whatever the subject puts in it is recorded as-is.

Nothing here renames anything. Rows keep the exact keys the collector wrote;
`alias_of` records how a field RELATES to a core field without touching either.
Renaming would be a form of the editing this whole package exists to prevent.

The entries themselves live in a profile, not here: which fields exist is one
programme's schema, while the idea of a registered extension is everyone's.
"""

from typing import Dict, NamedTuple, Optional

VERBATIM = "verbatim"        # the subject's own structure or vocabulary
PROVENANCE = "provenance"    # how we came to record something
BATCH_LEVEL = "batch-level"  # a fact about the batch, repeated on each row
ANNOTATION = "annotation"    # a one-off note; a candidate for removal


class ExtensionField(NamedTuple):
    kind: str
    alias_of: Optional[str]
    note: str


def ext(kind: str, alias_of: Optional[str], note: str) -> ExtensionField:
    """Declare one extension field. Used by profiles to build their registry."""
    return ExtensionField(kind, alias_of, note)




def aliases_of(core_field: str, registry: Dict[str, ExtensionField]) -> Dict[str, ExtensionField]:
    """Every registered field that relates to a given core field."""
    return {n: f for n, f in registry.items() if f.alias_of == core_field}


def by_kind(kind: str, registry: Dict[str, ExtensionField]) -> Dict[str, ExtensionField]:
    return {n: f for n, f in registry.items() if f.kind == kind}
