"""This suite must not shrink silently.

A module that fails to import is replaced by one synthetic `_FailedTest`, so N real tests become 1
error and the count drops with nothing naming what went missing. It happened here: an indentation
error left three tests uncollected, and the only reason it surfaced was counting `def test_` against
what actually ran.

Discovery runs in a subprocess deliberately. Discovering a suite from inside itself is order- and
path-dependent -- importing a test module runs its module-level `sys.path.insert`, so a second
in-process discover resolves against a path the first did not have.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Raise when tests are added. Never lower it to make a red suite green: a drop means tests stopped
# being collected, which is the failure this file exists to catch.
COLLECTED_FLOOR = 66

_PROBE = """
import json, unittest
def leaves(s):
    for x in s:
        if isinstance(x, unittest.TestSuite):
            yield from leaves(x)
        else:
            yield x
tests = list(leaves(unittest.TestLoader().discover("tests", pattern="test_*.py")))
print(json.dumps({
    "collected": len(tests),
    "failed": [t.id() for t in tests if type(t).__name__ == "_FailedTest"],
}))
"""


@lru_cache(maxsize=1)
def _discover() -> dict:
    proc = subprocess.run([sys.executable, "-c", _PROBE], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"test discovery itself failed:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class SuiteIntegrity(unittest.TestCase):
    def test_no_module_fails_to_import(self) -> None:
        broken = _discover()["failed"]
        self.assertEqual(broken, [], "a test module failed to import: " + "; ".join(broken))

    def test_collected_count_has_not_dropped(self) -> None:
        collected = _discover()["collected"]
        self.assertGreaterEqual(
            collected,
            COLLECTED_FLOOR,
            f"collects {collected} tests but the floor is {COLLECTED_FLOOR}; find out which module "
            "stopped importing before touching this number",
        )


if __name__ == "__main__":
    unittest.main()
