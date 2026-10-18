"""Remediation report — the checker's output to the maker.

A verdict says a batch failed. It does not say what to do about it, and the
difference matters: spec §5 routes a failed gate back to the **planner**, never
to the executor, because "try again" is the retry loop and the retry loop is
where gaming begins.

So this report separates findings into two kinds, and the split is the whole
point:

  structural — cannot be fixed by editing rows. A missing capture is not a
               defect in the staging file; it is an absent Bronze artifact.
               Editing rows to make the gate pass would be fabrication.

  fixable    — the rows disagree with the contract or with their own evidence,
               and correcting them is legitimate work.

A maker agent handed only "G3 FAILED, 14 rows" will edit 14 quotes until the
gate goes green. That is the failure this whole package exists to prevent, so
the report never says what failed without saying what may legitimately change.
"""

import json
import random
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import __version__
from .gates import g1_capture, g2_conformance, g3_grounding, g4_completeness
from .manifest import MANIFEST, MANIFEST_SHA256
from .manifest import sha256_file
from .parsing import parse_staging
from .verdict import Verdict, utc_now_iso, write_verdict

STRUCTURAL = "structural"
FIXABLE = "fixable"
PLANNER = "planner"

# Orthogonal to the kind above, and the maker needs both to act.
#
#   GAP   — something is absent. It cannot be corrected by changing what is
#           there; it has to be produced, or its absence recorded as a decision.
#   ISSUE — something is present and wrong. It can be corrected in place.
#
# Conflating them is how "fix the failures" becomes "edit rows until green": a
# missing capture and a mistyped quote both read as "G3 FAILED" without this.
GAP = "gap"
ISSUE = "issue"

GAP_CODES = {
    "capture_missing", "capture_empty", "capture_hash_absent", "bronze_missing",
    "staging_missing", "denominator_missing", "empty_denominator",
    "rows_file_missing", "stops_file_missing", "root_missing",
    "no_declared_pages", "no_source_quote", "no_source_url",
    "index_item_without_row", "stop_condition_without_reason",
    "zero_rows", "nothing_checked", "robots_unreachable",
    "batch_unchecked", "capture_has_no_page_blocks",
    "unfetchable_source",
    "completeness_unassessable", "no_exhaustion_evidence",
    "window_declaration_incomplete", "window_end_undeclared",
    "collection_parked", "window_chain_gap", "window_ended_in_error",
    "subject_missing", "input_missing", "reference_empty", "map_id_missing",
}


def nature_of(code: str) -> str:
    return GAP if code in GAP_CODES else ISSUE


class Remedy(NamedTuple):
    kind: str
    text: str


REMEDIES: Dict[str, Remedy] = {
    "capture_missing": Remedy(
        STRUCTURAL,
        "No capture exists for this batch. The rows cannot be grounded — not by "
        "this tool and not by a reader. Either re-collect the batch with a "
        "fetcher that writes `_capture-<batch>.raw.txt`, or record the batch as "
        "unverifiable. Do NOT edit rows to make this pass; there is nothing to "
        "check them against.",
    ),
    "capture_empty": Remedy(
        STRUCTURAL,
        "The capture exists but holds no text. Re-fetch and write a new dated "
        "file. Bronze is never edited in place.",
    ),
    "bronze_missing": Remedy(
        STRUCTURAL,
        "A Bronze artifact is absent. Bronze is not reconstructable by editing; "
        "re-fetch and write a new dated file.",
    ),
    "marker_unbalanced": Remedy(
        STRUCTURAL,
        "The capture's BEGIN/END markers are unbalanced, so page blocks cannot "
        "be delimited. The capture is corrupt: re-fetch. Do not hand-repair it.",
    ),
    "duplicate_page_block": Remedy(
        STRUCTURAL,
        "The same URL is captured more than once. Re-fetch the batch cleanly "
        "rather than deleting one block by hand.",
    ),
    "staging_missing": Remedy(
        STRUCTURAL,
        "No staging file exists for this batch. Either the batch name is wrong "
        "or the row-writer never ran. Check the name against the vendor "
        "directory before concluding the rows are missing.",
    ),
    "denominator_missing": Remedy(
        STRUCTURAL,
        "No denominator file, so coverage cannot be measured against anything. "
        "Capture the vendor's own index surface first — a denominator invented "
        "from our expectations measures our plan, not their product.",
    ),
    "rows_file_missing": Remedy(
        STRUCTURAL,
        "A rows file named on the command line does not exist. This is a "
        "run-configuration fault, not a data fault: correct the path and re-run "
        "before reading anything into the result.",
    ),
    "stops_file_missing": Remedy(
        STRUCTURAL,
        "The stop-conditions file named does not exist. Either the path is "
        "wrong or no stop-conditions were recorded for this vendor; the two are "
        "not the same and should not be conflated.",
    ),
    "root_missing": Remedy(
        STRUCTURAL,
        "The project root given does not exist, so nothing was inspected. "
        "Correct the path — an integrity check that examined no files is not a "
        "clean integrity check.",
    ),
    "robots_unreachable": Remedy(
        STRUCTURAL,
        "robots.txt could not be fetched. This is not permission to proceed. "
        "Retry later; if it stays unreachable, treat the vendor as closed.",
    ),
    "verdict_unreadable": Remedy(
        STRUCTURAL,
        "A recorded verdict cannot be parsed, so its claim about the batch is "
        "unavailable. Re-run the gate that produced it rather than assuming the "
        "batch was previously green.",
    ),

    "capture_hash_absent": Remedy(
        FIXABLE,
        "Staging frontmatter has no `source_capture_sha256`. Add it, computed "
        "from the capture this batch was written from.",
    ),
    "frontmatter_unparseable": Remedy(
        FIXABLE,
        "The staging frontmatter cannot be read, so the batch's own claims "
        "about its provenance are unavailable. Correct it to `key: value` lines "
        "with list items as `  - item`.",
    ),
    "pages_not_a_list": Remedy(
        FIXABLE,
        "`pages:` must be a list of the URLs this batch declares, one per line "
        "as `  - <url>`. Without it G1 cannot check that what was cited is what "
        "was fetched.",
    ),
    "non_row_object": Remedy(
        FIXABLE,
        "An object in the rows block carries none of `id`, `source_url` or "
        "`source_quote`, so it is not a row — typically batch metadata sitting "
        "inside the same fence. Move it to the frontmatter, where batch facts "
        "belong, or leave it and accept that this batch reports one finding "
        "per run. It is NOT a malformed row, and the rows around it are "
        "unaffected.",
    ),
    "row_unparseable": Remedy(
        FIXABLE,
        "The row is not valid JSON, so it was never checked by the other gates. "
        "Correct the serialisation — an unparseable row is not a passing row.",
    ),
    "schema_violation": Remedy(
        FIXABLE,
        "The row disagrees with the contract. Correct the row — or, if the "
        "contract is wrong, change `models.py` deliberately with a version bump "
        "and a note in `_DECISIONS-OPEN.md`. Never mid-run.",
    ),
    "no_source_url": Remedy(
        FIXABLE,
        "Every row cites the page it came from. Add `source_url`, pointing at "
        "the page whose captured text contains the quote — not at a plausible "
        "page that happens to be about the same feature.",
    ),
    "no_source_quote": Remedy(
        FIXABLE,
        "Every row carries a verbatim quote. If the page does not say it, the "
        "row is not supported and should be dropped, not paraphrased.",
    ),
    "proof_unparseable": Remedy(
        FIXABLE,
        "The GOLD file's `proof:` line cannot be read, so its row count cannot "
        "be checked against its content. Restore it to a form that states the "
        "count plainly.",
    ),
    "stop_condition_without_reason": Remedy(
        FIXABLE,
        "Every stop-condition states why. \"We stopped\" is not a reason.",
    ),

    # --- grounding: where gaming is most likely, so the remedies are explicit
    "quote_not_in_capture": Remedy(
        FIXABLE,
        "The quote does not appear in the page it cites. Legitimate fixes: "
        "replace the quote with text the page actually contains, or drop the "
        "row. Illegitimate: editing the quote until it matches something, "
        "anything, elsewhere in the capture. If the page does not support the "
        "claim, the claim is not supported — a paraphrase presented as a quote "
        "is the exact defect this gate exists to catch.",
    ),
    "quote_from_wrong_page": Remedy(
        FIXABLE,
        "The quote exists in the capture but in a different page's block. The "
        "row is misattributed: correct `source_url` to the page the text is "
        "actually on. Do not leave the citation pointing at a page that does "
        "not contain the quote.",
    ),
    "capture_has_no_page_blocks": Remedy(
        STRUCTURAL,
        "The capture holds text but no `=====BEGIN <url>=====` markers, so it "
        "cannot be split into pages. These rows are **unassessable, not "
        "ungrounded** — nothing has been shown wrong with them; grounding simply "
        "could not be attempted. Re-fetch the batch with a fetcher that writes "
        "per-page markers. Do not edit the rows, and do not accept a "
        "whole-capture match as grounding: without page boundaries a quote "
        "lifted from a different page is indistinguishable from a correct one.",
    ),

    "url_not_in_capture": Remedy(
        PLANNER,
        "The row cites a URL with no block in the capture. Either the page was "
        "never fetched — add it to the fetch list and re-run the fetcher — or "
        "the URL is invented.",
    ),

    # --- role separation and provenance: not repairable by editing rows
    "role_collapse": Remedy(
        STRUCTURAL,
        "The staging file attests `fetched_by_this_agent: true` — one agent both "
        "fetched and wrote rows. Attestation is not the problem; the collapse "
        "is. Re-collect with a fetcher and a row-writer that has no `WebFetch`. "
        "Clearing the flag hides the collapse instead of fixing it.",
    ),
    "capture_hash_mismatch": Remedy(
        STRUCTURAL,
        "The staging file's `source_capture_sha256` does not match the capture "
        "on disk. The rows were written from different bytes than the ones "
        "present. Re-run the row-writer against this capture; do not simply "
        "update the hash to match.",
    ),
    "capture_not_before_staging": Remedy(
        STRUCTURAL,
        "The capture is newer than the staging file, so the rows cannot have "
        "been written from it. Re-run the row-writer against the current "
        "capture. Touching timestamps changes the evidence, not the fact.",
    ),
    "bronze_modified": Remedy(
        STRUCTURAL,
        "A Bronze artifact changed after it was written. Bronze is never edited "
        "— not for a typo, not for whitespace. Re-fetch into a new dated file "
        "and leave the original alone.",
    ),
    "bronze_touched_after_verdict": Remedy(
        STRUCTURAL,
        "A Bronze file was modified after a verdict was recorded against it. "
        "Every verdict citing it is now void. Re-fetch, then re-run the gates.",
    ),
    "manifest_mismatch": Remedy(
        STRUCTURAL,
        "The recorded verdicts were produced by different gate code than is now "
        "installed. This is the tamper-evidence signal firing. Establish which "
        "version is approved, then re-run the gates from it. Do not reconcile "
        "by editing the recorded manifest.",
    ),
    "site_wide_disallow": Remedy(
        STRUCTURAL,
        "robots.txt disallows one of our agents (Claude-User or ClaudeBot) "
        "site-wide. This is terminal for the "
        "vendor: no retry, no alternate fetcher, no different user-agent. "
        "Record the stop reason and close the vendor.",
    ),

    # --- the checks that report on the checking itself
    "zero_rows": Remedy(
        STRUCTURAL,
        "No rows were parsed. A parser that sees nothing and a file that holds "
        "nothing look identical, so this is treated as a defect rather than an "
        "empty pass. Confirm the file has rows and that `parsing.py` reads this "
        "serialisation before concluding anything about the data.",
    ),
    "parser_disagrees_with_naive_count": Remedy(
        STRUCTURAL,
        "The structured parse and the naive count disagree, so one of them is "
        "wrong and the gate cannot say which. This is a tooling fault, not a "
        "data fault — do not edit rows to reconcile it. Fix `parsing.py`.",
    ),
    "row_unparseable_not_checked": Remedy(
        STRUCTURAL,
        "Rows failed to parse and were therefore never checked. Their absence "
        "from the findings is not evidence they are sound.",
    ),
    "nothing_checked": Remedy(
        STRUCTURAL,
        "The gate ran but examined nothing. An empty check is not a pass — "
        "treat this as a failure of the run, not a clean result.",
    ),

    # --- contract and completeness
    "duplicate_id": Remedy(
        FIXABLE,
        "Two rows share an `id`. An id identifies one node in the tree, so a "
        "duplicate means either two nodes were given the same name or one node "
        "was recorded twice. Establish which before renaming: silently "
        "suffixing the second one preserves a duplicate rather than resolving it.",
    ),
    "no_declared_pages": Remedy(
        FIXABLE,
        "The staging frontmatter declares no pages, so G1 cannot check that "
        "what was cited was what was fetched. Add the `pages:` list.",
    ),
    "empty_denominator": Remedy(
        STRUCTURAL,
        "The denominator holds no index items, so coverage is unmeasurable. "
        "Re-capture the index surface.",
    ),
    # --- one feature, several sources (same_feature_as) and ways in --------
    "same_feature_as_invalid": Remedy(
        FIXABLE,
        "`same_feature_as` names the row id of another row of the same feature — "
        "its anchor. Write that id, or remove the field when this row is the "
        "feature's first row.",
    ),
    "same_feature_unknown": Remedy(
        FIXABLE,
        "`same_feature_as` names a row id the subject does not have. Copy the "
        "anchor's id from the batch's FEATURES.md or this batch's own rows; if "
        "the feature has no row yet, this row is its anchor — remove the field.",
    ),
    "same_feature_not_anchor": Remedy(
        FIXABLE,
        "`same_feature_as` names a row that is itself another source. Name the "
        "anchor that row points to: every source of a feature points at the one "
        "anchor, never along a chain.",
    ),
    "interface_type_unknown": Remedy(
        FIXABLE,
        "`interface_type` is one of `API`, `SDK`, `webhook`, `CLI` or `user "
        "interface`, spelled exactly so.",
    ),
    "interface_without_type": Remedy(
        FIXABLE,
        "A row naming an `operation` or `parameter` says which way in it "
        "documents, in `interface_type`.",
    ),
    "map_line_for_another_source": Remedy(
        FIXABLE,
        "A row with `same_feature_as` takes its anchor's classification and has "
        "no mapping line. Remove its line from the mapping file; the rows are "
        "not changed.",
    ),
    "tree_same_feature_dangling": Remedy(
        STRUCTURAL,
        "A tree row points at a feature the tree does not have. /kbqa-merge "
        "refuses that, so the tree was changed outside it: a human compares the "
        "tree with its merge log before anything else merges.",
    ),
    "proof_count_mismatch": Remedy(
        FIXABLE,
        "The GOLD file's `proof:` count disagrees with its own content. Correct "
        "the count to match the rows actually present.",
    ),
    # --- "were the gates actually run?" — the control that stands in for a
    # required status check when the estate repo cannot enforce one.
    "batch_unchecked": Remedy(
        FIXABLE,
        "No verdict records this staging file, so the gates never ran on it. "
        "Run `kbqa report --vendor-dir <dir> --batch <name>`. An unchecked batch "
        "is not a passing batch — its absence from the findings says nothing "
        "about it.",
    ),
    "verdict_stale": Remedy(
        FIXABLE,
        "Every verdict for this batch was recorded against different bytes than "
        "the file now holds: it was checked, then changed. Re-run the gates. The "
        "recorded PASS refers to a file that no longer exists.",
    ),
    "batch_known_failing": Remedy(
        PLANNER,
        "This batch has a current FAIL verdict and is still in the estate. Its "
        "own report says what to do; this finding exists so a estate-wide sweep "
        "cannot quietly pass while a known-bad batch sits in it.",
    ),

    "term_at_multiple_urls": Remedy(
        PLANNER,
        "Advisory only. The same term appears at several URLs, which is an R2 "
        "question about naming, not a defect. Do not resolve it by guessing a "
        "relationship — a `usecase_of` inferred from string similarity is "
        "indistinguishable later from a sourced one.",
    ),

    "page_not_in_capture": Remedy(
        PLANNER,
        "The row cites a page that is not in the capture. Either the page was "
        "never fetched — add it to the fetch list and re-run the fetcher — or "
        "the citation does not correspond to anything fetched, in which case "
        "the row is unsupported. Changing the quote to match a different page "
        "is not a fix.",
    ),
    "index_item_without_row": Remedy(
        PLANNER,
        "An index item has no row citing it. Plan a batch covering it, or "
        "record a stop-condition with a stated reason. Do not lower the "
        "denominator to close the gap.",
    ),
    "completeness_unassessable": Remedy(
        PLANNER,
        "Nothing establishes how much of this subject exists, so nothing can "
        "say how much of it we hold. Capture the subject's own index as a "
        "denominator — that is the preferred fix. Where the surface publishes "
        "no index, declare `window_requested` and `window_returned` per batch "
        "so exhaustion can be evidenced instead. Leaving both absent does not "
        "make the subject complete; it makes completeness unknown.",
    ),
    "no_exhaustion_evidence": Remedy(
        PLANNER,
        "Windows were declared but none came back empty. A window returning "
        "fewer items than it asked for is not proof the list ended — it is "
        "equally consistent with a run that stopped early. Probe one more "
        "window and record the result, even when you are confident it will be "
        "zero. Do NOT infer the end from a short return.",
    ),
    "window_underwritten": Remedy(
        FIXABLE,
        "The batch declares more items returned than it holds rows, and no "
        "stop-condition accounts for the rest. Either write the missing rows; or, "
        "for a returned page that holds nothing to record, add `<url> | no "
        "feature: <what the page is>` keyed by its URL; or correct the declaration "
        "if it over-counted — but establish which before changing anything. "
        "Lowering `window_returned` to match the rows makes the finding disappear "
        "without recovering the items.",
    ),
    "unfetchable_source": Remedy(
        FIXABLE,
        "The row cites a source nobody else can retrieve — a `doc:` reference, "
        "a local path, a filename. It could never be grounded: G3 looks for the "
        "cited URL as a page block in the capture, and an unfetchable reference "
        "by construction is not one, so this row was already failing, just "
        "further downstream and less legibly. Capture the document like any "
        "other page and cite the URL it was served from. Where that is "
        "impossible, the row is an assertion rather than evidence and belongs "
        "out of the corpus or in a recorded decision — not re-labelled to pass.",
    ),
    "collection_parked": Remedy(
        PLANNER,
        "Not a defect. A large index cannot be taken in one pass, and a "
        "collector that stopped on its budget did the right thing — the "
        "alternative is a run killed mid-surface whose partial output looks "
        "complete. The subject is simply not finished: schedule the next window "
        "from the offset in the message. Do NOT mark the subject done, and do "
        "not treat the parked window as the end of the list.",
    ),
    "window_end_undeclared": Remedy(
        FIXABLE,
        "A window that does not say why it ended cannot be interpreted. Twelve "
        "returned against twenty asked means either the source had twelve or "
        "the collector stopped at twelve — opposite situations needing opposite "
        "responses. Record window_end as `exhausted`, `budget` or `error`, from "
        "what actually happened.",
    ),
    "window_end_unknown_value": Remedy(
        FIXABLE,
        "window_end must be `exhausted` (the source ran out), `budget` (the "
        "collector stopped deliberately) or `error` (the attempt failed). A "
        "fourth value is not a fourth outcome; pick the one that describes what "
        "happened.",
    ),
    "window_chain_gap": Remedy(
        PLANNER,
        "Consecutive windows skip a range, so those items were never requested "
        "— absent from the corpus without ever having been looked at. Collect "
        "the missing range as its own window. Do not renumber the offsets to "
        "make the chain contiguous; that hides the gap rather than closing it.",
    ),
    "window_ended_in_error": Remedy(
        PLANNER,
        "The window failed partway, so the range beyond it is unattempted "
        "rather than absent. Re-run that window. An errored window is never "
        "evidence that the list ended.",
    ),
    "window_declaration_incomplete": Remedy(
        FIXABLE,
        "Half a window declaration cannot distinguish exhaustion from "
        "abandonment. Record both `window_requested` and `window_returned`, "
        "from what the source actually returned — not from what was written.",
    ),
}

# --- K1 · rules for batches under the current naming convention ----------
REMEDIES.update({
    "id_not_first_key": Remedy(
        FIXABLE,
        "Write `id` as the first key of the row. Nothing else in the row changes.",
    ),
    "parent_path_empty": Remedy(
        FIXABLE,
        "Copy the page's own breadcrumb or navigation trail verbatim from that "
        "page's block in the capture. If the page shows none, write `unknown`. "
        "Never build one from the URL or the title, and never leave it empty.",
    ),
    "depth_unknown_with_breadcrumb": Remedy(
        FIXABLE,
        "The page shows a breadcrumb, so its depth is known: count the "
        "breadcrumb's levels and write that number, or the level the page names. "
        "`unknown` is for a page that shows no hierarchy at all.",
    ),
    "evidence_grade_spelling": Remedy(
        FIXABLE,
        "Use the schema's spelling of the grade (official-doc | help | marketing "
        "| verified | [verify]). The grade itself does not change.",
    ),
    # --- K2 · mandatory surfaces ------------------------------------------
    "surface_missing": Remedy(
        PLANNER,
        "Collect the surface — capture its own index as "
        "`_denominator-<surface>-<date>.md` — or, if the subject does not publish "
        "it, record `<url> | surface <slug> not published: <what that page "
        "shows>` citing a fetched page. \"Not found\" is unfinished, not a stop.",
    ),
    "surface_unfinished": Remedy(
        PLANNER,
        "The surface has a denominator but no batch. Run its windows until the "
        "source returns nothing, or park with an offset.",
    ),
    "surface_contradiction": Remedy(
        PLANNER,
        "A surface cannot be both indexed and unpublished. A human reads both "
        "files and decides which is wrong; neither is deleted to clear this.",
    ),
    "surface_stop_without_page": Remedy(
        PLANNER,
        "Key the stop-condition by the URL of the fetched page that shows the "
        "surface is absent, so a reader can check it.",
    ),
    # --- K4 · stranded batches ---------------------------------------------
    "clear_not_merged": Remedy(
        PLANNER,
        "The batch is CLEAR and its rows are not in the tree. The operator runs "
        "`/kbqa-merge` for it. Nobody else merges.",
    ),
    "clear_partially_merged": Remedy(
        PLANNER,
        "Some of the batch's ids are in the tree and some are not. Stop: a human "
        "compares the two before any merge. Never renumber ids to clear this.",
    ),
    # --- K2 · surfaces: the run itself -------------------------------------
    "subject_missing": Remedy(
        STRUCTURAL,
        "The path given is not a subject folder. Pass `Competitors/<Subject>/` as "
        "it exists on disk; nothing was checked, so nothing is clean.",
    ),
    # --- K5 · mapping files: the run itself --------------------------------
    "input_missing": Remedy(
        STRUCTURAL,
        "One of the files the check needs — the staging file, a mapping file, the "
        "codebook or the element list — was not found at the path given. Nothing "
        "was checked. Pass the path that exists; do not create an empty file.",
    ),
    "too_many_maps": Remedy(
        STRUCTURAL,
        "A batch has at most two mapping files, A and B. Pass those two; a third "
        "pass is not a tie-breaker.",
    ),
    "reference_empty": Remedy(
        STRUCTURAL,
        "The codebook gave no theme codes or the element list gave no elements, "
        "so there was nothing to check the mapping against. Point at the real "
        "reference files; nothing was checked.",
    ),
    # --- K5 · mapping files: one line per staging row ----------------------
    "map_id_missing": Remedy(
        FIXABLE,
        "A staging row has no line in this mapping file. The mapping pass writes "
        "one line for it — `needs-human` with a note if it cannot be mapped. "
        "Never drop the row from staging to clear this.",
    ),
    "map_id_not_in_staging": Remedy(
        FIXABLE,
        "The mapping file has a line for an id that is not a row of this batch. "
        "Remove that line from the mapping file; the batch's rows are not changed.",
    ),
    "map_id_duplicate": Remedy(
        FIXABLE,
        "An id has more than one line. Keep one line per staging id; a second "
        "reading belongs in the other mapping file (A or B), not in this one.",
    ),
    "map_line_unparseable": Remedy(
        FIXABLE,
        "The line is not a JSON object. Rewrite it as one JSON object on one line.",
    ),
    "map_id_not_first": Remedy(
        FIXABLE,
        "Write `id` as the first key of the mapping line. Nothing else changes.",
    ),
    "map_fields_mismatch": Remedy(
        FIXABLE,
        "The line must carry exactly the mapping format's fields — id, user_story, "
        "role, role_source, actor, theme, theme_links, pcf_ids, confidence, "
        "status, note — none missing, none extra.",
    ),
    "map_null_value": Remedy(
        FIXABLE,
        "A field is null. An empty value is `\"\"` for text and `[]` for a list.",
    ),
    "map_type": Remedy(
        FIXABLE,
        "`theme_links` and `pcf_ids` are lists. Write them as JSON arrays, `[]` "
        "when empty.",
    ),
    # --- K5 · mapping files: codes must exist ------------------------------
    "theme_unknown": Remedy(
        FIXABLE,
        "`theme` must be a code from the codebook's table, or NONE, NO-FUNCTION or "
        "NOT-FEATURE. A theme the codebook lacks is a question for the operator, "
        "so mark the line `needs-human` with a note; never add the code here.",
    ),
    "theme_link_unknown": Remedy(
        FIXABLE,
        "Every `theme_links` entry must be a code from the codebook's table. Remove "
        "the entry, or mark the line `needs-human` with a note.",
    ),
    "pcf_entry_shape": Remedy(
        FIXABLE,
        "Each `pcf_ids` entry is exactly `{pcf_id, hierarchy_id, name}`, in that "
        "order, copied from the element list.",
    ),
    "pcf_unknown": Remedy(
        FIXABLE,
        "The `pcf_id` is not in the element list, so it does not exist. Use an id "
        "from the list, or mark the line `needs-human` with a note.",
    ),
    "pcf_not_copied": Remedy(
        FIXABLE,
        "The `hierarchy_id` or `name` differs from the element list for that id. "
        "Copy both from the list exactly; they are never retyped.",
    ),
    "role_source_empty": Remedy(
        FIXABLE,
        "Fill `role_source`: `rbac-row`, `rbac-vendor:<row id>` or `apqc-closest`. "
        "It may be empty only when `theme` is NO-FUNCTION or NOT-FEATURE.",
    ),
    "role_source_invalid": Remedy(
        FIXABLE,
        "`role_source` must be `rbac-row`, `rbac-vendor:<row id>` or "
        "`apqc-closest`, written exactly so.",
    ),
    "role_source_row_unknown": Remedy(
        FIXABLE,
        "`rbac-vendor:<row id>` names a row this subject does not have. Cite an "
        "existing row id of the subject, or use another role source.",
    ),
    "actor_invalid": Remedy(
        FIXABLE,
        "`actor` is one of A, B, C, D, E — or empty only when `theme` is "
        "NO-FUNCTION or NOT-FEATURE.",
    ),
    "confidence_invalid": Remedy(
        FIXABLE,
        "`confidence` is `low`, `medium` or `high`, written exactly so — the "
        "mapping pass's own confidence in that line.",
    ),
    "status_invalid": Remedy(
        FIXABLE,
        "`status` is `mapped` or `needs-human`, written exactly so. A line that "
        "cannot be mapped is `needs-human` with a note, never left blank.",
    ),
    "needs_human_without_reason": Remedy(
        FIXABLE,
        "A `needs-human` line says why in `note`, so the operator knows what to "
        "decide. Write the reason; do not change the status to clear this.",
    ),
    "needs_human_without_pattern": Remedy(
        FIXABLE,
        "A `needs-human` note opens with the rule or open pattern it stops on, in "
        "brackets, as the logic sheet names it (`[<name>] …`), so the check groups "
        "the rows and the operator answers each question once. Name it; do not "
        "change the status to clear this.",
    ),
    "story_role_mismatch": Remedy(
        FIXABLE,
        "The `user_story` opens \"As <role>, I want\" (with \"a\" or \"an\" for a "
        "singular role) and that role is the line's `role`, word for word, "
        "singular or plural as printed; an APQC-closest role is followed by "
        "\"(APQC-closest)\", and no other is. Write the story with the role from "
        "its source; never change `role` to match a story.",
    ),
    # --- K5 · mapping files: the whole batch -------------------------------
    "element_dominates": Remedy(
        PLANNER,
        "One APQC element is on more than 30 % of the batch's rows. A human reads "
        "a sample of those rows before the batch is accepted. Do not spread rows "
        "across other elements to clear this.",
    ),
})

DEFAULT_REMEDY = Remedy(FIXABLE, "See the finding message.")

KIND_HEADING = {
    STRUCTURAL: "Structural — must NOT be fixed by editing rows",
    PLANNER: "For the planner — scope or fetch-list changes",
    FIXABLE: "Fixable — correct and re-run",
}

KIND_ORDER = (STRUCTURAL, PLANNER, FIXABLE)


# K6 · rows shown to the operator per report, chosen with a seed derived from
# the staging file's own hash: the same bytes always give the same sample, and
# a changed file gives a new one. The seed is printed so anyone can redraw it.
SAMPLE_SIZE = 10

NOT_CHECKED = "NOT CHECKED"
PARKED = "PARKED"


def fix_round(log: Optional[Path], batch: str, staging_sha: Optional[str]) -> Tuple[Optional[int], int]:
    """K3 · Which check round this is, from the log's recorded staging hashes.

    Round 1 is the first set of bytes ever checked; each later, different set
    of bytes is one more round. Re-running on unchanged bytes is the same round.
    Returns (round or None without a log, earlier runs that carried no hash).
    """
    if log is None or staging_sha is None:
        return None, 0
    shas: List[str] = []
    unhashed = 0
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("batch") != batch or d.get("gate") != "g2_conformance":
                continue
            sha = (d.get("inputs") or {}).get("staging")
            if not sha:
                unhashed += 1
            elif sha not in shas:
                shas.append(sha)
    if staging_sha not in shas:
        shas.append(staging_sha)
    return shas.index(staging_sha) + 1, unhashed


def operator_sample(vendor_dir: Path, batch: str, staging: Path) -> dict:
    """K6 · A fixed-seed random sample of rows: quote, claim and mapping.

    The gates check that a quote is real and on its page; they cannot check
    that it supports the claim. These rows are for the operator's eye.
    """
    if not staging.exists():
        return {"seed": None, "size": 0, "rows": []}
    sha = sha256_file(staging)
    seed = int(sha[:8], 16)
    objs = [r.obj for r in parse_staging(staging).rows if r.obj and r.obj.get("id")]
    picked = sorted(random.Random(seed).sample(range(len(objs)), min(SAMPLE_SIZE, len(objs))))
    maps: Dict[str, Dict[str, dict]] = {}
    for letter in ("A", "B"):
        mp = vendor_dir / f"_map-{batch}-{letter}.jsonl"
        if mp.exists():
            maps[letter] = {}
            for line in mp.read_text(encoding="utf-8").splitlines():
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(o, dict) and o.get("id"):
                    maps[letter][str(o["id"])] = o
    rows = []
    for i in picked:
        o = objs[i]
        rows.append({
            "id": o.get("id"), "vendor_term": o.get("vendor_term"),
            "claim": o.get("what_it_does"), "source_quote": o.get("source_quote"),
            "source_url": o.get("source_url"),
            "mapping": {k: m.get(str(o.get("id"))) for k, m in maps.items()},
        })
    return {"seed": seed, "seed_from": f"sha256(staging)[:8] = {sha[:8]}",
            "size": len(rows), "of_rows": len(objs), "maps": sorted(maps), "rows": rows}


def _run(mod, argv: List[str]) -> Tuple[Verdict, int]:
    result = mod.run(argv)
    return result[0], result[1]


def _gate_sha(gate: str) -> str:
    """The hash of the module that produced a finding — per-finding provenance."""
    return MANIFEST.get(f"gates/{gate}.py", "unknown")[:12]


def build(
    vendor_dir: Path,
    batch: str,
    denominator: Optional[Path] = None,
    stops: Optional[Path] = None,
    log: Optional[Path] = None,
) -> Tuple[str, List[Tuple[Verdict, int]], int, dict]:
    """Run the batch gates and render a report.

    Returns (markdown, results, exit_code, machine_readable).
    """
    staging = vendor_dir / f"_collect-{batch}-staging.md"
    capture = vendor_dir / f"_capture-{batch}.raw.txt"

    results: List[Tuple[Verdict, int]] = [
        _run(g1_capture, ["--staging", str(staging), "--capture", str(capture)]),
        _run(g2_conformance, ["--staging", str(staging)]),
        _run(g3_grounding, ["--staging", str(staging), "--capture", str(capture)]),
    ]
    # A gate that did not run is a hole in the check, not a silent pass. Record
    # why, so the report never implies coverage it does not have.
    not_run: List[Tuple[str, str]] = []
    if denominator is not None:
        argv = ["--denominator", str(denominator), "--rows", str(staging)]
        if stops is not None:
            argv += ["--stops", str(stops)]
        results.append(_run(g4_completeness, argv))
    else:
        # K2 · coverage belongs to a SURFACE, not to one window of it. A batch
        # holding window 2 of 5 legitimately cites a fifth of the index; judged
        # alone against the whole denominator it could never be CLEAR, and so
        # could never merge. Coverage is therefore measured once per surface,
        # over all its batches — and this line says where, so its absence here
        # is never read as coverage measured.
        not_run.append((
            "g4_completeness",
            "no --denominator given, so coverage against the subject's own index "
            "was not measured for this batch. Coverage is a surface-level measure: "
            "`kbqa g4 --denominator <surface denominator> --rows <every batch of "
            "the surface>`. This batch may be internally consistent and still miss "
            "most of the surface.",
        ))
    not_run.append((
        "g5_bundles",
        "advisory gate, run separately with `kbqa g5 --rows <f>...`",
    ))
    not_run.append((
        "g6_integrity",
        "estate-wide, run separately with `kbqa g6 --root <project>`",
    ))

    worst = max(code for _, code in results)
    blocked = any(v.verdict == "FAIL" for v, _ in results)

    # K7 · a gate that ran over nothing has not checked anything.
    not_checked = [v.gate for v, _ in results if v.counts.get("scanned") == 0]
    staging_sha = sha256_file(staging) if staging.exists() else None
    round_no, unhashed_runs = fix_round(log, batch, staging_sha)
    sample = operator_sample(vendor_dir, batch, staging)

    # Collect findings with their provenance and classification.
    items: List[dict] = []
    for verdict, _ in results:
        for f in verdict.findings:
            remedy = REMEDIES.get(f.code, DEFAULT_REMEDY)
            items.append({
                "code": f.code,
                "gate": verdict.gate,
                "gate_sha256": _gate_sha(verdict.gate),
                "kind": remedy.kind,
                "nature": nature_of(f.code),
                "remedy": remedy.text,
                "message": f.message,
                "where": f.where,
            })

    lines: List[str] = []
    a = lines.append

    fixable_n = len([i for i in items if i["kind"] == FIXABLE])
    if not_checked:
        status = NOT_CHECKED
    elif blocked and round_no is not None and round_no >= 2 and fixable_n:
        status = PARKED
    elif blocked:
        status = "BLOCKED"
    else:
        status = "CLEAR"

    a(f"# QA report — {vendor_dir.name} / {batch}")
    a("")
    a(f"**{status}** · {len(items)} finding(s) · round "
      f"{round_no if round_no is not None else 'unknown (no --log)'}")
    a("")
    if not_checked:
        a(f"⚠ **NOT CHECKED** — scanned 0 items: {', '.join(f'`{g}`' for g in not_checked)}. "
          "An empty check is not a pass, and this batch is not CLEAR.")
        a("")
    if status == PARKED:
        a(f"⛔ **PARKED** — round {round_no} still has {fixable_n} fixable finding(s). "
          "The one fix round is used. Nothing goes back to the row-writer without "
          "the operator; the finding list below is theirs.")
        a("")
    a("| | |")
    a("|---|---|")
    a(f"| generated | `{utc_now_iso()}` |")
    a(f"| kbqa version | `{__version__}` |")
    a(f"| manifest | `{MANIFEST_SHA256}` |")
    a(f"| directory / batch | `{vendor_dir.name}` / `{batch}` |")
    a(f"| staging | `{staging.name}` |")
    a(f"| capture | `{capture.name}`{'' if capture.exists() else ' — **absent**'} |")
    a("")

    a("## For the maker")
    a("")
    a("Everything below is work on **your** side of the boundary: the estate, "
      "the captures, the rows. None of it is work on the checker.")
    a("")
    a(f"The gates that produced these findings are pinned at manifest "
      f"`{MANIFEST_SHA256[:16]}…`, and each finding names the exact module and "
      "hash that raised it. If you believe a gate is wrong, say so and cite that "
      "hash — do not edit the gate to make a batch pass. A verdict from edited "
      "code is distinguishable from a verdict from approved code, which is the "
      "point of recording the hash at all.")
    a("")
    a("Route through the **planner**, not straight back to the executor. "
      "\"Try again\" is the retry loop, and the retry loop is where gaming "
      "begins. (§5)")
    a("")

    a("## Coverage — what was and was not checked")
    a("")
    a("| gate | module | verdict | scanned | rows | failed |")
    a("|---|---|---|---|---|---|")
    for verdict, _ in results:
        c = verdict.counts
        shown = NOT_CHECKED if verdict.gate in not_checked else verdict.verdict
        a(
            f"| `{verdict.gate}` | `{_gate_sha(verdict.gate)}` | "
            f"**{shown}** | {c.get('scanned', '–')} | {c.get('rows', '–')} | {c.get('failed', '–')} |"
        )
    for gate, why in not_run:
        a(f"| `{gate}` | – | _not run_ | – | – | – |")
    g2c = next((v.counts for v, _ in results if v.gate == "g2_conformance"), {})
    if g2c:
        a("")
        a(f"K1 rules for new batches: **{g2c.get('strict_rules', 'unknown')}** "
          f"(surface `{g2c.get('surface', '?')}`, {g2c.get('strict_checked', 0)} row(s)).")
    a("")
    for gate, why in not_run:
        a(f"- **`{gate}` did not run** — {why}")
    a("")
    a("A gate that did not run has found nothing, which is not the same as "
      "having found nothing wrong.")
    a("")

    gaps = [i for i in items if i["nature"] == GAP]
    issues = [i for i in items if i["nature"] == ISSUE]

    a("## Summary")
    a("")
    a("| | gaps (absent) | issues (present but wrong) |")
    a("|---|---|---|")
    for kind in KIND_ORDER:
        g = len([i for i in gaps if i["kind"] == kind])
        s = len([i for i in issues if i["kind"] == kind])
        a(f"| {kind} | {g} | {s} |")
    a("")
    a("**Gaps** cannot be corrected by changing what is there — something has to "
      "be produced, or its absence recorded as a decision. **Issues** are "
      "present and wrong, and can be corrected in place. Treating a gap as an "
      "issue is how \"fix the failures\" becomes \"edit rows until green\".")
    a("")

    if not items:
        a("## Action plan")
        a("")
        a("Nothing to do for the gates that ran.")
        a("")
        if blocked:
            a("⚠ A gate reported FAIL with no findings. That is a defect in the "
              "gate, not a clean batch — do not read it as a pass.")
            a("")
    else:
        a("## Action plan")
        a("")
        a("Ordered so that nothing depends on work further down the list.")
        a("")
        step = 0
        for kind in KIND_ORDER:
            for nature in (GAP, ISSUE):
                bucket = [i for i in items if i["kind"] == kind and i["nature"] == nature]
                if not bucket:
                    continue
                by_code: Dict[str, List[dict]] = {}
                for i in bucket:
                    by_code.setdefault(i["code"], []).append(i)
                for code, entries in sorted(by_code.items()):
                    step += 1
                    e0 = entries[0]
                    a(f"### {step}. `{code}` — {len(entries)} occurrence(s)")
                    a("")
                    a(f"- **class**: {kind} · **nature**: {nature}")
                    a(f"- **raised by**: `{e0['gate']}` (`{e0['gate_sha256']}`)")
                    a("")
                    a(f"**Do this.** {e0['remedy']}")
                    a("")
                    a("**Occurrences**")
                    a("")
                    for i in entries[:25]:
                        where = f"`{i['where']}` — " if i["where"] else ""
                        a(f"- {where}{i['message']}")
                    if len(entries) > 25:
                        a(f"- … and {len(entries) - 25} more, in `_qa/{batch}.{e0['gate']}.json`")
                    a("")
        a("**Verify by re-running the same command.** A finding is resolved when "
          "it stops appearing — not when it is explained.")
        a("")

    a("## Operator sample — quote, claim, mapping")
    a("")
    if sample["size"]:
        a(f"{sample['size']} of {sample['of_rows']} rows, seed `{sample['seed']}` "
          f"({sample['seed_from']}). Mapping files read: "
          f"{', '.join(sample['maps']) or 'none yet'}. The gates cannot see whether a "
          "quote supports its claim; these rows are for a human to read.")
        a("")
        for n, s in enumerate(sample["rows"], 1):
            a(f"**{n}. `{s['id']}`** — {s['vendor_term']}")
            a(f"- claim: {s['claim']}")
            a(f"- quote: \"{s['source_quote']}\"")
            a(f"- source: {s['source_url']}")
            for letter, m in sorted(s["mapping"].items()):
                if m is None:
                    a(f"- mapper {letter}: _no line for this id_")
                else:
                    pcf = "; ".join(f"{p.get('pcf_id')} {p.get('name')}" for p in (m.get("pcf_ids") or [])
                                    if isinstance(p, dict)) or "—"
                    a(f"- mapper {letter}: {m.get('status')} · theme {m.get('theme')} · {pcf} · "
                      f"\"{m.get('user_story')}\"")
            a("")
    else:
        a("No rows to sample.")
        a("")

    a("## Provenance")
    a("")
    a(f"- kbqa `{__version__}`, manifest `{MANIFEST_SHA256}`")
    a(f"- full verdicts: `_qa/{batch}.<gate>.json`")
    a(f"- machine-readable copy of this report: `_qa/{batch}.report.json`")
    a("")
    a("Every verdict carries the manifest hash of the code that produced it, so a "
      "verdict from edited gates is distinguishable from one from approved gates. "
      "That is what makes this tamper-evident rather than merely tidy — and it is "
      "why fixing a batch by editing the checker leaves a trace.")
    a("")

    machine = {
        "kbqa_version": __version__,
        "manifest_sha256": MANIFEST_SHA256,
        "batch": batch,
        "generated": utc_now_iso(),
        "status": status,
        "round": round_no,
        "earlier_runs_without_hash": unhashed_runs,
        "not_checked": not_checked,
        "staging_sha256": staging_sha,
        "sample": {**{k: v for k, v in sample.items() if k != "rows"},
                   "ids": [s["id"] for s in sample["rows"]]},
        "exit_code": worst,
        "gates_run": [
            {
                "gate": v.gate,
                "gate_sha256": _gate_sha(v.gate),
                "verdict": v.verdict,
                "counts": v.counts,
            }
            for v, _ in results
        ],
        "gates_not_run": [{"gate": g, "reason": w} for g, w in not_run],
        "counts": {
            "findings": len(items),
            "gaps": len(gaps),
            "issues": len(issues),
            **{k: len([i for i in items if i["kind"] == k]) for k in KIND_ORDER},
        },
        "findings": items,
    }

    return "\n".join(lines) + "\n", results, worst, machine


def run(argv: List[str]) -> int:
    vendor_dir = batch = out = None
    denominator = stops = None
    log = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if arg == "--vendor-dir" and nxt:
            vendor_dir = Path(nxt); i += 2; continue
        if arg == "--batch" and nxt:
            batch = nxt; i += 2; continue
        if arg == "--denominator" and nxt:
            denominator = Path(nxt); i += 2; continue
        if arg == "--stops" and nxt:
            stops = Path(nxt); i += 2; continue
        if arg == "--log" and nxt:
            log = Path(nxt); i += 2; continue
        if arg == "--out" and nxt:
            out = Path(nxt); i += 2; continue
        print(f"report: unexpected argument {arg!r}")
        return 1

    if not vendor_dir or not batch:
        print("report: need --vendor-dir <dir> --batch <name>")
        return 1
    if not vendor_dir.is_dir():
        print(f"report: not a directory: {vendor_dir}")
        return 1

    markdown, results, code, machine = build(vendor_dir, batch, denominator, stops, log)

    for verdict, _ in results:
        write_verdict(verdict, vendor_dir, batch, log)

    target = out or (vendor_dir / "_qa" / f"{batch}.report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")

    # Sidecar for a maker agent that consumes the plan rather than reading it.
    sidecar = target.with_suffix(".json")
    sidecar.write_text(json.dumps(machine, indent=2, default=str) + "\n", encoding="utf-8")

    print(f"report written: {target}")
    print(f"machine-readable: {sidecar}")
    for verdict, _ in results:
        print(f"  {verdict.gate:<16} {verdict.verdict}")
    c = machine["counts"]
    print(f"  status={machine['status']}  round={machine['round']}  "
          f"sample_seed={machine['sample'].get('seed')}")
    if machine["not_checked"]:
        print(f"  NOT CHECKED (scanned 0): {', '.join(machine['not_checked'])}")
    # The counts the collecting agents no longer give by hand (v6.18.0): the
    # check is the one counter of rows and of distinct terms (spec §3).
    stg = vendor_dir / f"_collect-{batch}-staging.md"
    if stg.exists():
        rows = [r.obj for r in parse_staging(stg).rows if r.obj is not None]
        terms = {str(r.get("vendor_term")) for r in rows if r.get("vendor_term")}
        print(f"  rows={len(rows)}  distinct_vendor_terms={len(terms)}")
        # One feature, several sources: features are counted once (their
        # anchors); the other sources and the ways in are counted apart.
        others = [r for r in rows if r.get("same_feature_as")]
        ways_in = {(str(r.get("source_url")), str(r.get("operation") or ""))
                   for r in rows if r.get("interface_type")}
        print(f"  features={len(rows) - len(others)}  other_sources={len(others)}  interfaces={len(ways_in)}")
    print(
        f"  findings={c['findings']}  gaps={c['gaps']}  issues={c['issues']}  "
        f"structural={c['structural']}  planner={c['planner']}  fixable={c['fixable']}"
    )
    return code
