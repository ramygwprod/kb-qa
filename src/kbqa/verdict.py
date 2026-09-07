"""Verdict records. Gates read only, and write only these.

Every verdict carries the manifest hash of the code that produced it (spec §3)
and every run appends one line to _qa-log.jsonl (spec §6).
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .manifest import MANIFEST_SHA256, sha256_file

PASS = "PASS"
FAIL = "FAIL"
ADVISORY = "ADVISORY"
DECLINED = "DECLINED"
ERROR = "ERROR"


def utc_now_iso() -> str:
    """UTC timestamp. KBQA_RUN_AT pins it so fixtures are byte-reproducible."""
    pinned = os.environ.get("KBQA_RUN_AT")
    if pinned:
        return pinned
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def input_ref(path: Path) -> Dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {"path": str(p), "sha256": None, "present": False}
    return {"path": str(p), "sha256": sha256_file(p), "present": True}


@dataclass
class Finding:
    code: str
    message: str
    where: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"code": self.code, "message": self.message}
        if self.where is not None:
            d["where"] = self.where
        return d


@dataclass
class Verdict:
    gate: str
    verdict: str
    inputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    counts: Dict[str, Any] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "gate": self.gate,
            "kbqa_version": __version__,
            "manifest_sha256": MANIFEST_SHA256,
            "inputs": self.inputs,
            "counts": self.counts,
            "findings": [f.to_dict() for f in self.findings],
            "verdict": self.verdict,
            "run_at": utc_now_iso(),
        }
        if self.extra:
            d.update(self.extra)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False, default=str)


def write_verdict(
    verdict: Verdict,
    vendor_dir: Optional[Path],
    batch: str,
    log_path: Optional[Path] = None,
    vendor: Optional[str] = None,
) -> Optional[Path]:
    """Write _qa/<batch>.<gate>.json and append one line to _qa-log.jsonl.

    Both are append-only by convention: a verdict file is named for the batch
    and gate that produced it, and re-running overwrites only that pair.
    Returns the verdict path, or None when no vendor_dir was given.
    """
    out_path = None
    if vendor_dir is not None:
        qa_dir = Path(vendor_dir) / "_qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        out_path = qa_dir / f"{batch}.{verdict.gate}.json"
        out_path.write_text(verdict.to_json() + "\n", encoding="utf-8")

    if log_path is not None:
        d = verdict.to_dict()
        line = {
            "ts": d["run_at"],
            "vendor": vendor,
            "batch": batch,
            "gate": verdict.gate,
            "verdict": verdict.verdict,
            "rows": verdict.counts.get("rows"),
            "failed": verdict.counts.get("failed"),
            "kbqa": d["kbqa_version"],
            "manifest": d["manifest_sha256"],
        }
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, default=str) + "\n")

    return out_path
