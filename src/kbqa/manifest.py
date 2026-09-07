"""SHA-256 of every gate module, computed at import.

This is the whole tamper-evidence design: a verdict records the hash of the
code that produced it, so a verdict from edited code is DISTINGUISHABLE from a
verdict from approved code.

⛔ This makes tampering visible, not impossible. It is spec level 1
(tamper-evident). Only CI re-running the gates from a pinned version (level 4)
is tamper-proof. Do not describe this module as making anything "uneditable".
"""

import hashlib
from pathlib import Path
from typing import Dict

_PKG_ROOT = Path(__file__).resolve().parent

# Every source file whose behaviour can change a verdict.
_MANIFEST_GLOBS = ("*.py", "gates/*.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest() -> Dict[str, str]:
    """Map of package-relative module path -> sha256, sorted by path."""
    found = {}
    for pattern in _MANIFEST_GLOBS:
        for path in _PKG_ROOT.glob(pattern):
            if path.name == "__pycache__":
                continue
            rel = path.relative_to(_PKG_ROOT).as_posix()
            found[rel] = sha256_file(path)
    return dict(sorted(found.items()))


def manifest_digest(manifest: Dict[str, str]) -> str:
    """One hash over the whole manifest. Order-independent by construction."""
    payload = "\n".join(f"{path}:{digest}" for path, digest in sorted(manifest.items()))
    return sha256_bytes(payload.encode("utf-8"))


MANIFEST: Dict[str, str] = compute_manifest()
MANIFEST_SHA256: str = manifest_digest(MANIFEST)
