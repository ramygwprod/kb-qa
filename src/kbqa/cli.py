"""python -m kbqa <gate> [args]

The CLI prints the verdict JSON to stdout and exits with the gate's code.
Verdict files and the compliance log are written only when asked for, so a
gate run is side-effect-free by default.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__, freeze, probe, profile, report, sweep
from .gates import g0_permission, g1_capture, g2_conformance
from .gates import g3_grounding, g4_completeness, g5_bundles, g6_integrity
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
  g6 --root <project>                          integrity

recording args (optional, apply to every gate):
  --vendor-dir <dir>   write _qa/<batch>.<gate>.json under this directory
  --batch <name>       batch name used in the verdict filename
  --log <path>         append one line to this _qa-log.jsonl

cycle:
  report --vendor-dir <d> --batch <name> [--denominator <f>] [--stops <f>]
                                               run G1-G3 (+G4), write a
                                               remediation report for the maker
  sweep  --root <estate> [--field-values]      audit the whole estate: which
                                               batches can be checked at all

diagnostics:
  probe --staging <f> [--capture <f>]          report file SHAPE, not content
  freeze --root <d> --out <f>                  fingerprint the subject's own words
  freeze --root <d> --check <f>                did interpreting the data change it?

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

    # Estate-wide audit. Records what can be checked; does not gate.
    if argv[0] == "sweep":
        return sweep.run(argv[1:])

    # Records a fingerprint of the subject's own words, and compares later.
    # Answers "did interpreting the data change it", which no gate asks.
    if argv[0] == "freeze":
        return freeze.run(argv[1:])

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
