"""
DOD idempotency check: run QuestionBank.generate() twice against the real parts
dir and verify the sha256 of questions.json is identical both times.

Prints 'same' if identical, 'DIFF' if not.

Usage:
    python3 tests/coverage/_check_idempotent.py
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

# Allow invocation by absolute script path (the form the DoD uses):
# put the repo root on sys.path so `import tests.coverage.*` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PARTS_DIR = Path(__file__).parent / "parts"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    from tests.coverage.questions import QuestionBank

    bank = QuestionBank()

    with tempfile.TemporaryDirectory(prefix="coverage_idempotent_") as tmpdir:
        out1 = Path(tmpdir) / "questions1.json"
        out2 = Path(tmpdir) / "questions2.json"

        bank.generate(parts_dir=_PARTS_DIR, out_path=out1)
        bank.generate(parts_dir=_PARTS_DIR, out_path=out2)

        sha1 = _sha256(out1)
        sha2 = _sha256(out2)

        if sha1 == sha2:
            print("same")
        else:
            print(f"DIFF: run1={sha1} run2={sha2}")
            sys.exit(1)


if __name__ == "__main__":
    main()
