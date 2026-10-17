---
name: kbqa-collect
description: Collect one subject into the estate — plan, permission, capture, rows, then two independent classification passes — by delegating to the kbqa-fetcher, kbqa-row-writer and kbqa-mapper subagents. Also runs the one fix round for a batch the check blocked. Run by the operator as /kbqa-collect <Subject> [fix <batch>]. Never fetches or writes itself, never reads verdicts, never runs the gates.
allowed-tools: Task, Agent, Read
disable-model-invocation: true
---

# Collecting a subject

**Invoked as**, by the operator, in a session opened at the estate root:

| command | does |
|---|---|
| `/kbqa-collect <Subject>` | plan → approval → collect every surface → classify every new batch |
| `/kbqa-collect <Subject> fix <batch>` | the one fix round for a batch `/kbqa-check` reported BLOCKED (§6) |

You orchestrate. Every step is a delegation:

| subagent | holds | does |
|---|---|---|
| `kbqa-fetcher` | `WebFetch`, `Write`, `Read`, `Bash` | permission, indexes, captures, stop-conditions, receipts |
| `kbqa-row-writer` | `Read`, `Write` | rows, from the capture on disk alone |
| `kbqa-mapper` | `Read`, `Write` | one classification pass of one batch |

**You do not fetch, write or run commands yourself, even if this session lets
you.** The skill's tool list pre-approves `Task`, `Agent` and `Read`; it does not
take the other tools away, so this is a rule you keep, not a wall.

## 0 · Pre-flight and configuration

1. Delegate to `kbqa-fetcher` its pre-flight (its §0). On any `STOP`, stop and
   give the operator the printed command.
2. Read `kbqa-estate.json` at the estate root. It must name, relative to the
   estate root: `subjects_dir`, `logic_sheet`, `themes_codebook`,
   `apqc_elements`, `field_schema`. If the file or any key is missing, or a named
   file does not exist, stop and name exactly what is missing. Never guess a path.

The subject's folder is `<subjects_dir>/<Subject>/`. Read that path: an error
saying it is a directory means it exists; any other error means it does not —
say so and ask the operator to create it, before anything is delegated (G0
creates the folder it is given, so a misspelt name would become a new folder).
Never invent a location.

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
item count) or its stop-condition; the hosts in scope, each with the page that
links to it, and any host whose ownership is unclear; hosts whose robots.txt
stayed unreachable; the crawl delay; PDFs found; the language version. **Then
stop and wait for explicit approval.** No page content is fetched before it.
PDFs, non-English pages and any host the plan did not name need their own
approval.

**A subject that no longer operates** — the fetched pages show it closed, shut
down or gone: stop here. No plan, no denominator, no tree. Tell the operator
what the pages show; recording it is the operator's.

## 2 · Collect each approved surface, window by window

Batch names: `<surface>-<YYYY-MM-DD>-wNN` (`w01`, `w02`, …), the date being the
fetcher's access date from the plan. Before each window, find the next free
number by Read alone (`Read` cannot list a folder): from `w01` upward, Read
`<subject folder>/_capture-<batch>.raw.txt` and
`<subject folder>/_collect-<batch>-staging.md` with `limit: 1`; the first number
for which **both** Reads fail as absent is the next batch. **A batch name is never
reused.**

Per window:

1. `kbqa-fetcher`: one window — batch, surface, offset, approved scope. It
   returns a receipt (its §6).
2. `kbqa-row-writer`: the capture **path** and the receipt values. It returns
   the rows written and the **pages that produced no row**. Never pass page
   content through you.
3. `kbqa-fetcher` again, only if step 2 named pages with no row: it records
   `no feature: <what the page is>` for each (its §4).
4. Read `window_end`: `exhausted` — the surface is done; `budget` — next window;
   `error` — report and stop this surface. **Never write or infer `exhausted`.**
   A host that will not load is never worked around: stop that surface and ask
   the operator.

## 3 · Close the surface's coverage

When a surface is `exhausted`, every item in its denominator must be either
cited by a row or covered by a stop-condition keyed by its URL — that is what
`/kbqa-check` measures. Ask `kbqa-fetcher` to compare the denominator with the
surface's captures and stop-conditions (its §5b) — give it the path of every
capture this run wrote for the surface — and record the stop for any
item that is neither. An item left out of scope on purpose needs the operator's
word first.

## 4 · Classify each new batch — two independent passes

For every batch written in this run, spawn `kbqa-mapper` **twice, separately**:
once with pass `A`, once with pass `B`. Give each the staging file path, its
letter, the three configured paths (`logic_sheet`, `themes_codebook`,
`apqc_elements`), and — for finding a role only — the subject's
`feature-tree.md` path and the path of every staging file this run wrote.

The passes are independent: never give one pass the other's file or output,
never summarise one to the other, and never start B with anything A said.
Agreement between two passes that saw each other measures nothing. Each writes
`_map-<batch>-<A|B>.jsonl`.

Rows a pass cannot map are `needs-human`, with a note. They are questions for
the operator, never forced.

## 5 · Report and stop

Return:

- subject and folder
- per surface: the index or its stop-condition; one line per window — batch,
  offset, requested, returned, `window_end`, rows; then `exhausted` or parked at
  which offset
- capture paths and sha256 values; fetch failures; redirects; every
  stop-condition added
- per batch: rows and distinct `vendor_term`s; **evidence not captured** and
  **role stated elsewhere**, as the row-writer listed them
- per batch: map files written, and each pass's `needs-human` ids with their notes
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

- **WebFetch is lossy by design** (Claude Code docs): Claude receives a model's
  rendering of the page, not its raw text, so a capture can differ from the
  live page. The operator sample in each `/kbqa-check` report is where a human
  compares them.
- **Nothing checks that a quote supports its claim**, and two passes agreeing is
  consistency, not correctness.
- **Coverage is measured against the index we captured.** A selective index goes
  unnoticed, which is why it is captured before scope is decided.
