---
name: kbqa-collect
description: Collect one subject into the estate — plan, permission, capture, rows, then two independent classification passes — by delegating to the kbqa-fetcher, kbqa-row-writer and kbqa-mapper subagents. Also runs the one fix round for a batch the check blocked. Run by the operator as /kbqa-collect <Subject> [fix <batch>]. Never fetches or writes itself, never reads verdicts, never runs the gates.
allowed-tools: Task, Agent, Read
disable-model-invocation: true
---

# Collecting a subject

**This copy is kbqa-collect v6.21.0**, installed with kb-qa v6.21.0.

**Invoked as**, by the operator, in a session opened at the estate root:

| command | does |
|---|---|
| `/kbqa-collect <Subject>` | plan → approval → collect every surface → classify every new batch |
| `/kbqa-collect <Subject> fix <batch>` | the one fix round for a batch `/kbqa-check` reported BLOCKED (§6) |

You orchestrate. Every step is a delegation:

| subagent | holds | does |
|---|---|---|
| `kbqa-fetcher` | `WebFetch`, `Read`, `Bash` | permission, indexes, captures, staging by code (`kbqa stage`), stop-conditions (by `kbqa stop add`), receipts |
| `kbqa-row-writer` | `Read`, `Write` | drafts of rows, from the capture on disk alone |
| `kbqa-mapper` | `Read`, `Write` | one classification pass of one batch |

**You do not fetch, write or run commands yourself, even if this session lets
you.** The skill's tool list pre-approves `Task`, `Agent` and `Read`; it does not
take the other tools away, so this is a rule you keep, not a wall.

Three more rules for running the session:

- **Offer only what the agents can do.** Before you put an option to the
  operator, check that an agent's file says it can carry it out. If none can,
  say so; never offer an option that cannot run.
- **Scope is the operator's.** Propose it in chat, by the denominator's own line
  numbers; the operator approves or changes it. Never delegate a scope judgement
  to an agent — they are forbidden to make one.
- **Report from disk, never from memory.** After a delegation that was
  interrupted, failed or returned nothing, Read the files that step was to write,
  by their exact names, before you say what happened.
- **A blocker goes to the operator at once.** When an agent returns one, stop
  that step and show it: what failed (command, URL, message, word for word), its
  `next_step`, the `suggested_stop_line` and the `options` the command printed —
  or, where it gave none, the operator opening the URL themselves and telling
  you what it shows. You never choose among the options; the operator does. What the operator
  reports is their ruling (a scope decision or a stop reason), never a capture.
  Never wait on a step in silence.
- **Three tries of a step, then the operator.** Delegate the same step at most
  three times. If it still has not worked, it is a blocker: bring it to the
  operator with the options. Nothing is retried without limit — the commands
  bound their own attempts, and you bound yours.

## 0 · Pre-flight and configuration

1. Delegate to `kbqa-fetcher` its pre-flight (its §0). On any `STOP`, stop and
   give the operator the printed command. **Then compare versions:** the
   pre-flight prints `kbqa: v<version>`; if that is not the version this copy
   states at the top, stop — this session loaded an older copy of the skill than
   is installed. Tell the operator to close this session and start a new one.
2. Read `kbqa-estate.json` at the estate root. It must name, relative to the
   estate root: `subjects_dir`, `logic_sheet`, `themes_codebook`,
   `apqc_elements`. If the file or any key is missing, or a named file does not
   exist, stop and name exactly what is missing. Never guess a path. An optional
   key, `role_rows`, holds the estate's patterns for rows that name roles and
   permissions; `kbqa stage --lists` reads it itself and lists the candidates
   for the mappers. Without it the list is not written, and the fetcher's
   `--lists` result says why.
   The element list must have its outline beside it, `<list>.outline.md` (the
   list's name with `.outline.md` for `.jsonl`). If it is missing, stop and give
   the operator the command, run at the estate root:
   `python3 -m kbqa elements --outline <apqc_elements>`. The row
   fields are not configured: they are the row-writer's table, which the check's
   rules enforce.

The subject's folder is `<subjects_dir>/<Subject>/`. Read that path: an error
saying it is a directory means it exists; any other error means it does not —
say so and give the operator the exact command, run at the estate root:
`mkdir -p "<subjects_dir>/<Subject>"`, before anything is delegated (G0 creates
the folder it is given, so a misspelt name would become a new folder). Never
invent a location.

3. **A tree from before this pipeline.** Read `<subject folder>/feature-tree.md`
   and `<subject folder>/_merge-log.jsonl` (`limit: 5` each; a Read error means
   the file is absent). A tree with no merge log was not built by `/kbqa-merge`,
   and `/kbqa-merge` only appends: new rows would sit beside the old rows for the
   same features. **Stop** and tell the operator, before any plan:

   > `<Subject>` has a feature tree from before this pipeline and no merge log.
   > Collecting now would put new rows beside its old ones. Either move the tree
   > out of the subject folder (the first CLEAR batch then starts a new one with
   > `/kbqa-merge … --new-tree`), or confirm in words that the new rows go into
   > the old tree.

   Go on only on the operator's answer. A tree with a merge log is this
   pipeline's own; collect into it.

## 1 · Plan — delegate to `kbqa-fetcher`, then STOP for approval

The fetcher checks permission (G0) for every host it will touch, captures each
surface's own index as `_denominator-<surface>-<YYYY-MM-DD>.md`, and records a
stop-condition for each surface not published (its §1–§2).

Show the operator, per surface (`product`, `docs`, `help`): the index (rung, URL,
item count, and its `sections` — an llms.txt's own `##` headings, or groups by
host and path, each with its line ranges) or its stop-condition; **every host
the probe flagged** (`refused: HTTP 403` and the like — the host refuses our
fetcher — with whether its own copy answers), before scope is approved; the
hosts in scope, each with the page that
links to it, and any host whose ownership is unclear; hosts whose robots.txt
stayed unreachable; the crawl delay; PDFs found; the language version, and the
number of other-language copies the index left out because the English page
exists (the operator's rule: English is enough). **Then
stop and wait for explicit approval.** No page content is fetched before it.
PDFs, non-English pages and any host the plan did not name need their own
approval.

**Propose the scope from the sections, by line numbers or by path** (e.g.
"docs: lines 2–813", or "help: the items under `/hc/en-us/articles/`" — a path
selection, `--select-prefix`, when the items to keep are interleaved with
others), never by reading every item of a large denominator. Read individual
denominator lines only to answer the operator's question about them. The
approved selection is what every window of that surface is given. A
denominator that needs correcting the same day — a path prefix the operator
adds after seeing it — is rewritten only on the operator's word, by the
fetcher's `--supersede`: a new lettered file that names the one it supersedes.

**A subject that no longer operates** — the fetched pages show it closed, shut
down or gone: stop here. No plan, no denominator, no tree. Tell the operator
what the pages show; recording it is the operator's.

## 2 · Collect each approved surface, window by window

**Where a surface stands is read from disk, never remembered.** Before the first
window of a surface — in every run — have `kbqa-fetcher` report its status
(`kbqa capture --status`, its §3 — with `--files` when you need to know which
denominators, captures, staging and map files exist). If windows are already
recorded, show the operator: the current denominator, the windows so far, where
collection stopped (`resume_from`), whether the surface is `exhausted`, the
failed pages that can be retried, and the pages that need the operator. Continue only on the operator's word; never start a
surface again from the beginning.

Batch names (`<surface>-<YYYY-MM-DD>-wNN`) are chosen by `kbqa capture`; a batch
name is never reused. Batch dates follow the access date: a surface collected
across midnight goes on in batches of the new date, and `kbqa capture` runs G0
itself for the new day — nothing to re-delegate.

Per window:

1. `kbqa-fetcher`: one window — surface, the denominator path, and either the
   approved selection (the surface's first window) or `--resume` (every later
   window, in this run or a later one). `kbqa capture` names the batch, slices and
   sizes the window, and records it; the fetcher returns its receipt (its §6).
2. `kbqa-fetcher`: `kbqa stage --lists` for the batch (its §3a) — the
   subject's features list, same-feature shortlist and role-row list beside
   the receipt, built now so
   they hold every row staged so far, earlier windows included. Keep the
   `role_rows` path or note it returns, for §4.
3. `kbqa-row-writer`: the subject folder and the **batch name — nothing else**.
   It reads the receipt from disk (`_raw/<batch>/RECEIPT.json`), so no window
   field, page table or part list passes through you, and none is retyped. It
   writes `_draft-<batch>.jsonl` — its judgement of each row, and the pages
   with no row — and returns the drafts path.
4. `kbqa-fetcher`: `kbqa stage` for the batch (its §3a). Code writes the
   staging file from the drafts and the receipt, and turns each page drafted
   with no row into a `no feature: …` line, which the fetcher adds with
   `kbqa stop add` (its §4). **A rejected draft blocks the staging file**: the
   fetcher returns the drafts it rejected — a quote not found once in its part,
   a field no row carries — each with its reason, the rejects file and the
   `round`.
5. Only if step 4 rejected drafts — **one correction round, never two**:
   `kbqa-row-writer` again, with the subject folder, the batch name and the
   rejects file (its §4a); it rewrites only the rejected lines of its drafts.
   Then `kbqa-fetcher` runs `kbqa stage` again. If drafts are still rejected,
   `kbqa-fetcher` runs `kbqa stage --leave-out-rejects`, as that result's
   `next_step` says: the staging file is written without them, and each is
   listed under `needs_operator` with its reason and a suggested next step —
   bring every one to the operator with the batch. Never a second correction
   round.
6. Read `window_end` — set by `kbqa capture`, never by an agent: `exhausted` —
   no selected item remains, the surface is done; `budget` — next window, with
   `--resume`; `error` — nothing in this window could be captured: stop this
   surface and bring the receipt's failures to the operator. The window is
   recorded, so the next run continues after it.
   A host that will not load is never worked around: stop that surface and ask
   the operator.
7. Bring every `needs_operator` item to the operator — a page no attempt can fix
   (a 404, a TLS failure, a host refusing our fetcher, a page failing in three
   runs), with its suggested stop line and options. One may close a whole
   surface on one host (`scope: surface`): a host that refused every page of the
   window after its own copy was tried. On the operator's word, `kbqa-fetcher`
   adds that exact line, or the operator opens the URL and rules on it.

**Failed pages.** When a surface's windows are done, if its receipts list failed
pages that may still pass (a timeout, a network error, throttling), offer the
operator one retry run: on a yes, `kbqa-fetcher` runs `--retry-failed`, which
retries each such page in at most three runs in all and then hands it to the
operator. The retry batch is written and classified like any other.

## 3 · Coverage is measured, not re-read

When a surface is `exhausted`, every item in its denominator must be either
cited by a row or covered by a stop-condition keyed by its URL — `/kbqa-check`
measures exactly that. Nobody re-reads the denominator against the captures:
the fetcher records each window's stop lines as they come, and items the
operator left out of the selection stay open in the check until they are
collected or ruled on. Report which surfaces are `exhausted` and which are
parked at which `next_offset`.

## 4 · Classify each new batch — two independent passes

For every batch written in this run, spawn `kbqa-mapper` **twice, separately**:
once with pass `A`, once with pass `B`. Give each the staging file path, its
letter, the configured paths (`logic_sheet`, `themes_codebook`,
`apqc_elements`) and the element list's outline, and — for finding a role only — the subject's
`feature-tree.md` path, the path of every staging file this run wrote, and the
batch's `role_rows` path (`_raw/<batch>/ROLE-ROWS.md`) when `kbqa stage --lists`
wrote one (step 2 of §2).

The passes are independent: never give one pass the other's file or output,
never summarise one to the other, and never start B with anything A said.
Agreement between two passes that saw each other measures nothing. Each writes
`_map-<batch>-<A|B>.jsonl`.

Rows a pass cannot map are `needs-human`, with a note that opens with the rule
or open pattern the row stops on, in brackets (`[<name>] …`). They are
questions for the operator, never forced, and `/kbqa-check` groups them into
one question per pattern. Passes hand back their `needs-human` ids and notes,
not counts: `/kbqa-check` counts.

## 5 · Report and stop

Return:

- subject and folder
- per surface: the index or its stop-condition; one line per window — batch,
  offset, requested, returned, `window_end`, rows; then `exhausted` or parked at
  which offset
- capture paths and sha256 values; fetch failures; redirects; every
  stop-condition added
- per batch: the staging path; the drafts `kbqa stage` rejected, with the
  row-writer's correction of each, and every draft left out with its reason;
  **evidence not captured** and **role stated elsewhere**, as the row-writer
  listed them
- per batch: map files written, and each pass's `needs-human` ids with their notes
- **no counts of rows, terms or mapped lines.** Nobody in this run counts by
  hand: `/kbqa-check` counts rows, distinct terms and each pass's `mapped` and
  `needs-human` lines from the files
- the next command: `/kbqa-check <subjects_dir>/<Subject>`, run by the operator
  in a new session

**Do not run the gates and do not report a verdict.** A collecting context that
sees its own verdict edits toward it.

## 6 · The fix round — `/kbqa-collect <Subject> fix <batch>`

Run only when the operator brings the `fixable` findings of a batch that
`/kbqa-check` reported BLOCKED in round 1. The operator pastes them; you never
open `_qa/` to find them.

1. Delegate to `kbqa-row-writer` in fix mode (its §5): the staging path, the
   capture path, and the findings, word for word.
2. If rows changed ids or were added or dropped, re-run both `kbqa-mapper` passes
   for that batch (§4). Otherwise the map files stand.
3. Report what changed, and stop. The operator runs `/kbqa-check` again: round 2.
   If it is still BLOCKED, it is PARKED with the operator — there is no third
   round, and you never start one.

Only `fixable` findings come through here. `structural` and `planner` findings
mean re-fetching or re-planning: a new batch, never an edit.

## 7 · Never

- fetch, write a file, or run a command yourself
- read `_qa/`, `_qa-log.jsonl` or any report or verdict
- reconstruct a page from memory, training data or another session
- compute a capture's sha256 anywhere but in `kbqa-fetcher`
- re-use a batch name, or prune a denominator to match what was fetched
- fetch content before the operator approved the plan
- let one classification pass see the other's work
- run a second fix round, or a fix round for a batch that is not BLOCKED

## Limits, so a clean run is not read as more than it is

- **A capture is the served HTML, rendered as text by code** (`kbqa capture`),
  with the raw bytes kept beside it. Content a page builds with JavaScript after
  loading is not in it: such a page is recorded `js-only`, never guessed at.
  The operator sample in each `/kbqa-check` report is still where a human
  compares a quote with the live page.
- **Nothing checks that a quote supports its claim**, and two passes agreeing is
  consistency, not correctness.
- **Coverage is measured against the index we captured.** A selective index goes
  unnoticed, which is why it is captured before scope is decided.
