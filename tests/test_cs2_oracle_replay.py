"""Byte-equality replay of a completed CS2 run.

The fixture under fixtures/oracle-talon/ is lifted verbatim from a real finished reconstruction
(.img2threejs/talon: 23/25 steps done, verdict pass, silhouetteIoU 0.9654). It is the correctness
oracle for extracting CS2 into its own plugin: if the review report drifts by a single byte during
that work, this fails.

Deliberately a byte comparison rather than a semantic one. A semantic assertion would have to
enumerate what matters, and the whole point of an oracle is to catch the change nobody predicted --
a reordered key, a dropped note, a float rendered to a different precision.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORACLE = Path(__file__).resolve().parent / "fixtures" / "oracle-talon"
CS2_REVIEW = ROOT / "stage4_review" / "cs2_review.py"


class Cs2OracleReplay(unittest.TestCase):
    def test_replaying_the_completed_run_reproduces_its_review_byte_for_byte(self) -> None:
        expected = (ORACLE / "cs2-review.json").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "replay.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(CS2_REVIEW),
                    "--manifest",
                    str(ORACLE / "cs2-intake.json"),
                    "--metrics",
                    str(ORACLE / "cs2-review-inputs.json"),
                    "--out",
                    str(out),
                ],
                cwd=ROOT.parent,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, f"cs2_review.py failed:\n{proc.stderr}")
            actual = out.read_bytes()

        self.assertEqual(
            actual,
            expected,
            "CS2 review output drifted from the recorded oracle. If the change was intentional, "
            "re-record the fixture in the same commit and say so -- do not relax this assertion.",
        )

    def test_the_oracle_records_a_passing_verdict(self) -> None:
        # Guards against the fixture being replaced by a failing run, which would make the byte
        # comparison above pass while proving nothing about a working pipeline.
        report = json.loads((ORACLE / "cs2-review.json").read_text())
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["failedGates"], [])
        self.assertGreaterEqual(report["metrics"]["silhouetteIoU"], 0.95)


if __name__ == "__main__":
    unittest.main()
