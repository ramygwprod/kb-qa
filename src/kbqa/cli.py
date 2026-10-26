"""python -m kbqa <gate> [args]

The CLI prints the verdict JSON to stdout and exits with the gate's code.
Verdict files and the compliance log are written only when asked for, so a
gate run is side-effect-free by default.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__, autofix, capture, collect_surface, elements, freeze, index, ledger, mappings, mapstage, probe, profile, report, stage, stops, sweep
from .gates import g0_permission, g1_capture, g2_conformance
from .gates import g3_grounding, g4_completeness, g5_bundles, g6_integrity
from .gates import mapcheck, surfaces
from .manifest import MANIFEST, MANIFEST_SHA256
from .verdict import write_verdict

GATES = {
    "g0": g0_permission,
    "g1": g1_capture,
    "g2": g2_conformance,
    "g3": g3_grounding,
    "g4": g4_completeness,
    "g5": g5_bundles,
    "g6": g6_integrity,
    # Not numbered gates, but they emit verdicts and take the recording flags.
    "surfaces": surfaces,
    "mapcheck": mapcheck,
}

USAGE = """kbqa {version} — validation gates for evidence-grounded collection

usage: python -m kbqa <gate> [gate args] [recording args]

gates:
  g0 --host <host> --out <vendor-dir>          permission     (exit 2 = DECLINED)
  g1 --staging <f> --capture <f>               capture integrity
  g2 --staging <f>                             conformance
  g3 --staging <f> --capture <f>               grounding
  g4 [--denominator <f>] --rows <f>... [--stops <f>]  completeness
       no --denominator: window mode, needs a terminal zero-return
  g5 --rows <f>...                             bundles (advisory, always exit 0)
  g6 --root <project>                          integrity (+ CLEAR batches not merged)
  surfaces --subject <d> [--stops <f>]         the three mandatory surfaces, per subject
  mapcheck --staging <f> --map <A> [--map <B>] --codebook <f> --elements <f> [--subject <d>]
                                               mapping files: well-formed, codes exist, A/B agreement

every check prints `scanned`; scanned 0 is NOT CHECKED, never clean

recording args (optional, apply to every gate):
  --vendor-dir <dir>   write _qa/<batch>.<gate>.json under this directory
  --batch <name>       batch name used in the verdict filename
  --log <path>         append one line to this _qa-log.jsonl

cycle:
  report --vendor-dir <d> --batch <name> [--denominator <f>] [--stops <f>] [--log <f>]
                                               run G1-G3 (+G4), write a
                                               remediation report for the maker;
                                               with --log: fix round, PARKED state
  sweep  --root <estate> [--field-values] [--recollect <f.jsonl>]
                                               audit the whole estate: which
                                               batches can be checked at all;
                                               --recollect writes the re-collection list
  autofix --subject <d> --batch <b>            before the row-writer's fix round: fix in the
                                               staging file only what code can fix exactly
                                               (a grade's spelling, parent_path and depth
                                               from the receipt, id first), on the report
                                               of its current bytes; every change recorded
                                               in _qa/<b>.autofix-<n>.json, the old bytes kept;
                                               run again on the bytes it wrote: "already
                                               applied", with what it left

ledger (read-only: writes nothing):
  status <subject dir> [--json]                what is left and what is done, by code: per
                                               surface items, captured, staged, rows (features /
                                               other sources), stop lines, open items (g4's own
                                               count), windows exhausted/parked/unstaged, pages
                                               to retry or given up; per batch the check on its
                                               current bytes (or not checked / stale), autofix
                                               records, map passes (made from the current
                                               staging?), merged or not; every needs-human map
                                               line grouped by its [pattern]
  status [<subject dir>] --estate <root>       the same questions across every subject of the
                                               estate's subjects_dir (kbqa-estate.json)
  status <subject dir> | --estate <root> --pattern "<name>"
                                               after a ruling: exactly the rows (batch, id,
                                               pass) whose needs-human note names the pattern,
                                               with the mapstage --reopen command per pass
                                               ("unknown" where the files cannot tell, never 0)

collection (the fetcher runs these; permission from today's g0 record, g0 run first when missing):
  index --out <d> --surface <s> --rung <n> --url <u> [--html] [--path-prefix <p>] [--supersede]
        [--all-languages]
                                               write a surface's denominator from
                                               the subject's own index, by code;
                                               sections and a probe per host for the plan
  capture --out <d> --surface <s> --denominator <f> [--select <lines> | --select-prefix <p>...]
          | --resume | --retry-failed | --status [--files]
                                               capture one window verbatim: raw
                                               bytes kept, text by a fixed rendering,
                                               the receipt in _raw/<batch>/RECEIPT.json
  collect-surface --out <d> --surface <s> --denominator <f> [--select <lines> | --select-prefix <p>...]
          [--max-windows <n>] [--max-pages <n>] [--max-chars <n>]
                                               capture's windows for one surface (the first,
                                               then --resume) until exhausted, throttled,
                                               refused, robots unreachable, a window that
                                               captured nothing, or --max-windows (10);
                                               then --retry-failed once when exhausted.
                                               One JSON: the windows, every window with a
                                               capture and no staging file (unstaged, from
                                               earlier runs too), the end state, one merged
                                               needs_operator and stop-line list
  stage --subject <d> --batch <b> --lists      before the row-writer: the subject's features
                                               and role-row lists beside the receipt;
                                               refused once the batch is staged
  stage --subject <d> --batch <b> [--leave-out-rejects]
                                               after it: the staging file from the
                                               row-writer's _draft-<batch>.jsonl — quotes
                                               copied from the capture, ids and the
                                               frontmatter by code; a rejected draft (or
                                               a page with no row and no reason, a link
                                               to no anchor, a value outside the profile)
                                               blocks it (one correction round, then
                                               --leave-out-rejects lists each left out);
                                               ROLE-ROWS.md refreshed after it is written
  mapstage --subject <d> --batch <b> --pass <A|B> --elements <list> [--leave-out-rejects]
                                               after each mapping pass: _map-<b>-<A|B>.jsonl
                                               from the mapper's _mapdraft-<b>-<A|B>.jsonl —
                                               user_story and each element's hierarchy id
                                               and name by code; a rejected line blocks it
                                               (one correction round, then
                                               --leave-out-rejects writes each anchor whose
                                               line is still rejected as needs-human)
  mapstage --subject <d> --batch <b> --pass <A|B> --retire [--no-record]
                                               fix round, after the anchor ids changed:
                                               move this pass's map, sidecar, draft and
                                               rejects into _qa/retired-<b>-<A|B>-<n>/;
                                               refused while the staging is unchanged or
                                               its anchor ids are; --no-record (operator's
                                               word only) retires a map with no sidecar
  mapstage --subject <d> --batch <b> --pass <A|B> --reopen "<pattern>"
                                               after the operator's ruling on a pattern (rows
                                               unchanged): retire this pass's files as --retire
                                               does, note REOPENED-FOR-RULING.txt, and write a
                                               new draft — every other line carried over
                                               exactly, a placeholder {{"id", "reopened"}} per
                                               needs-human line naming the pattern; a
                                               placeholder still there is a reject
  stop add <subject dir> "- <url> | <reason>"  append one stop line, atomically, if its
                                               reason is in the vocabulary
  stop reasons                                 print the stop-reason vocabulary

reference:
  elements --outline <elements.jsonl>         write <list>.outline.md: the top two
                                               levels with their line ranges, so a
                                               mapping pass reads only what it needs

diagnostics:
  probe --staging <f> [--capture <f>]          report file SHAPE, not content
  freeze --root <d> --out <f>                  fingerprint the subject's own words
  freeze --root <d> --check <f>                did interpreting the data change it?
  mappings --file <f> [--root <d>]             are the mapping statements well-formed?

profile (applies to every command):
  --profile <name>     the analytical framework to validate against
  --profiles           list available profiles and exit

other:
  --manifest           print the gate manifest and exit
  --version            print version and exit
""".format(version=__version__)


RECORDING_FLAGS = ("--vendor-dir", "--batch", "--log")


class Recording:
    def __init__(self):
        self.vendor_dir = None
        self.batch = None
        self.log = None

    def set(self, flag: str, value: Optional[str]) -> None:
        setattr(self, flag.lstrip("-").replace("-", "_"), value)


def split_recording_args(argv: List[str]):
    """Separate recording flags from gate flags.

    Done by hand rather than with argparse.parse_known_args, which mis-assigns
    values when unknown optionals precede known ones — that silently leaked
    --vendor-dir into the gate parsers and broke every two-argument gate.
    """
    rec = Recording()
    gate_argv: List[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        matched = False
        for flag in RECORDING_FLAGS:
            if arg == flag:
                rec.set(flag, argv[i + 1] if i + 1 < len(argv) else None)
                i += 2
                matched = True
                break
            if arg.startswith(flag + "="):
                rec.set(flag, arg.split("=", 1)[1])
                i += 1
                matched = True
                break
        if not matched:
            gate_argv.append(arg)
            i += 1
    return rec, gate_argv


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # --profile selects the analytical framework every gate validates against.
    # Taken before dispatch because it changes what a row IS, not how one gate
    # behaves — a verdict whose contract is ambiguous is worse than no verdict.
    if "--profile" in argv:
        i = argv.index("--profile")
        if i + 1 >= len(argv):
            print("--profile needs a name", file=sys.stderr)
            return 1
        name = argv[i + 1]
        try:
            profile.activate(name)
        except KeyError as exc:
            print(str(exc).strip("'\""), file=sys.stderr)
            return 1
        del argv[i:i + 2]

    if argv and argv[0] == "--profiles":
        for n, p in sorted(profile.available().items()):
            mark = "*" if n == profile.active().name else " "
            print(f"{mark} {n}\n    {p.description}")
        return 0

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv[0] == "--version":
        print(__version__)
        return 0
    if argv[0] == "--manifest":
        print(f"manifest_sha256 {MANIFEST_SHA256}")
        for path, digest in MANIFEST.items():
            print(f"{digest}  {path}")
        return 0

    # Not a gate: emits no verdict, writes nothing, and never exits 2.
    if argv[0] == "probe":
        return probe.run(argv[1:])

    # Runs several gates and renders their findings as remediation guidance.
    if argv[0] == "report":
        return report.run(argv[1:])

    # The fixes code can compute exactly from a report and the receipt, made
    # before the row-writer's fix round. Never a verdict.
    if argv[0] == "autofix":
        return autofix.run(argv[1:])

    # The subject ledger: what is left and what is done, computed from the
    # files. Read-only; never a verdict.
    if argv[0] == "status":
        return ledger.run(argv[1:])

    # Estate-wide audit. Records what can be checked; does not gate.
    if argv[0] == "sweep":
        return sweep.run(argv[1:])

    # Records a fingerprint of the subject's own words, and compares later.
    # Answers "did interpreting the data change it", which no gate asks.
    if argv[0] == "freeze":
        return freeze.run(argv[1:])

    # Collection, not gates: they fetch, under today's robots record, and write
    # a denominator or a capture. Never a verdict.
    if argv[0] == "index":
        return index.run(argv[1:])
    if argv[0] == "capture":
        return capture.run(argv[1:])
    # capture's windows for one surface, run until code says stop. Writes
    # nothing but what capture writes.
    if argv[0] == "collect-surface":
        return collect_surface.run(argv[1:])
    # The staging file written by code from the row-writer's drafts, and the
    # lists it reads. Never a verdict.
    if argv[0] == "stage":
        return stage.run(argv[1:])
    # A mapping file written by code from one pass's draft. Never a verdict.
    if argv[0] == "mapstage":
        return mapstage.run(argv[1:])
    # The stop-condition vocabulary, and the one atomic way to add a line.
    if argv[0] == "stop":
        return stops.run(argv[1:])
    # Derived reference: the APQC list's outline, so a mapping pass reads parts.
    if argv[0] == "elements":
        return elements.run(argv[1:])

    # Mapping statements: about rows, stored outside rows, keyed by id.
    # Checks that the file is well-formed. Never that a mapping is right.
    if argv[0] == "mappings":
        return mappings.run(argv[1:])

    gate_name = argv[0]
    if gate_name not in GATES:
        print(f"unknown gate {gate_name!r}\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        # Never exit 2 here. Exit 2 means DECLINED — a vendor closed to us.
        # A usage error must never be readable as a permission decision.
        return 1

    rec, gate_argv = split_recording_args(argv[1:])

    result = GATES[gate_name].run(gate_argv)
    verdict, code = result[0], result[1]

    print(verdict.to_json())

    if rec.vendor_dir or rec.log:
        batch = rec.batch or "unbatched"
        write_verdict(
            verdict,
            Path(rec.vendor_dir) if rec.vendor_dir else None,
            batch,
            Path(rec.log) if rec.log else None,
        )

    return code


if __name__ == "__main__":
    raise SystemExit(main())
