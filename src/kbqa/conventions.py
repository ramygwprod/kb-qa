"""On-disk conventions — how a corpus names and delimits its files.

These are decisions a collection programme makes, not facts about the world.
`_collect-<batch>-staging.md` and `=====BEGIN <url>=====` are one programme's
choices; another doing market intelligence on hiring, pricing or compliance
would reasonably choose differently and should not have to fork the gates to
say so.

Compiling them into the gates had a specific consequence worth remembering: a
discovery pattern that matches nothing looks exactly like a clean corpus. A
programme whose files were named differently would have got a green sweep over
zero batches.
"""

import re
from dataclasses import dataclass, field
from typing import Pattern


@dataclass(frozen=True)
class Conventions:
    """How to find and read the files of one collection programme."""

    # --- discovery -------------------------------------------------------
    staging_glob: str = "**/_collect-*-staging.md"
    staging_prefix: str = "_collect-"
    staging_suffix: str = "-staging.md"

    capture_template: str = "_capture-{batch}.raw.txt"
    capture_glob: str = "_capture-*.raw.txt"

    # `_denominator*.md`, not `_denominator-*.md`. The hyphenated form was
    # inferred from the specification; the corpus it validates writes the bare
    # `_denominator.md` 18 times out of 20. The narrower glob matched 2 files,
    # so G4 quietly did not run for 18 of 19 subjects — and a gate that did not
    # run reads as a Coverage line, not as a failure. (docs/DECISIONS.md D-009)
    denominator_glob: str = "_denominator*.md"
    robots_glob: str = "_robots-*.txt"
    stops_name: str = "_stop-conditions.md"
    gold_name: str = "feature-tree.md"

    verdict_dir: str = "_qa"
    log_name: str = "_qa-log.jsonl"
    audit_name: str = "_qa-estate-audit.md"

    # --- capture delimiters ----------------------------------------------
    # A capture must record WHICH page each span of text came from. The syntax
    # is arbitrary; the requirement is not. Without per-page delimiters a quote
    # cannot be tied to the page it cites, and grounding becomes impossible
    # rather than merely failing.
    begin_pattern: str = r"^=====BEGIN (?P<url>.+?)=====\s*$"
    end_pattern: str = r"^=====END (?P<url>.+?)=====\s*$"

    # --- identifiers ------------------------------------------------------
    # Derived from one corpus's ids, so it is a convention, not a law. A
    # programme addressing nodes by UUID, or one whose subjects legitimately
    # use uppercase, is not malformed — it is different, and would otherwise be
    # rejected by a rule inferred from whoever was collected first.
    #
    # The first segment once allowed `_` but not `-`, so `x_y` passed and `x-y`
    # failed. That cost 47 rows over a distinction with no reason behind it —
    # the third time this pattern rejected real ids for an arbitrary rule.
    id_pattern: str = r"^[a-z0-9_\-]+(\.[a-z0-9_\-]+)*$"

    # --- row serialisation ------------------------------------------------
    fence_open_pattern: str = r"^\s*```+\s*json\s*$"
    fence_close_pattern: str = r"^\s*```+\s*$"

    def batch_of(self, staging_name: str) -> str:
        """The batch name embedded in a staging filename."""
        n = staging_name
        if n.startswith(self.staging_prefix):
            n = n[len(self.staging_prefix):]
        if n.endswith(self.staging_suffix):
            n = n[: -len(self.staging_suffix)]
        return n

    def capture_for(self, batch: str) -> str:
        return self.capture_template.format(batch=batch)

    def staging_for(self, batch: str) -> str:
        return f"{self.staging_prefix}{batch}{self.staging_suffix}"

    @property
    def begin_re(self) -> Pattern:
        return re.compile(self.begin_pattern)

    @property
    def end_re(self) -> Pattern:
        return re.compile(self.end_pattern)

    @property
    def fence_open_re(self) -> Pattern:
        return re.compile(self.fence_open_pattern, re.IGNORECASE)

    @property
    def fence_close_re(self) -> Pattern:
        return re.compile(self.fence_close_pattern)


DEFAULT = Conventions()
