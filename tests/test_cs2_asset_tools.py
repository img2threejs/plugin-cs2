"""CLI contracts for the CS2 asset-acquisition tools.

Lifted verbatim from the base skill's test_pipeline.py when these three tools moved here. They shell
out to the tool the same way the base suite did, with the script path now resolved inside the plugin.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def run(script, *args):
    return subprocess.run(
        [sys.executable, str(TOOLS / script), *map(str, args)],
        capture_output=True,
        text=True,
    )


class Cs2AssetToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_fetch_cs2_metadata_resolves_and_flags_ambiguity(self):
        index = self.dir / "skins.json"
        index.write_text(json.dumps([
            {"name": "Karambit | Doppler (Phase 1)", "weapon": {"name": "Karambit"}, "paint_index": 415,
             "min_float": 0.0, "max_float": 0.08, "rarity": {"name": "Covert"}, "image": "https://example.test/1.png"},
            {"name": "Karambit | Doppler (Phase 2)", "weapon": {"name": "Karambit"}, "paint_index": 419,
             "min_float": 0.0, "max_float": 0.08, "rarity": {"name": "Covert"}, "image": "https://example.test/2.png"},
        ]))
        # ambiguous without --phase
        r = run("fetch_cs2_metadata.py", "--weapon", "Karambit", "--skin", "Doppler",
                 "--index-file", index)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ambiguous", r.stderr.lower())
        # disambiguated with --phase
        out = self.dir / "metadata.json"
        r = run("fetch_cs2_metadata.py", "--weapon", "Karambit", "--skin", "Doppler",
                 "--phase", "Phase 2", "--index-file", index, "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        record = json.loads(out.read_text())
        self.assertEqual(record["paintIndex"], 419)

    def test_fetch_cs2_metadata_paint_index_disambiguates_identical_names(self):
        # The real CSGO-API lists every Doppler phase under the SAME name, differing only by
        # paint_index -- so --phase (a name substring) cannot pick one, but --paint-index can.
        index = self.dir / "skins.json"
        # paint_index is a STRING in the real CSGO-API dataset -- match must handle that
        index.write_text(json.dumps([
            {"name": "★ Karambit | Doppler", "weapon": {"name": "Karambit"}, "paint_index": "418",
             "min_float": 0.0, "max_float": 0.08, "rarity": {"name": "Covert"}, "image": "https://example.test/418.png"},
            {"name": "★ Karambit | Doppler", "weapon": {"name": "Karambit"}, "paint_index": "419",
             "min_float": 0.0, "max_float": 0.08, "rarity": {"name": "Covert"}, "image": "https://example.test/419.png"},
        ]))
        # --phase "Phase 2" is not in these identical names at all -> no match, cannot help here
        no_match = run("fetch_cs2_metadata.py", "--weapon", "Karambit", "--skin", "Doppler",
                       "--phase", "Phase 2", "--index-file", index)
        self.assertNotEqual(no_match.returncode, 0)
        self.assertIn("no match", no_match.stderr.lower())
        # without --phase the two collide -> ambiguous, and the error lists each paint_index to pick from
        amb = run("fetch_cs2_metadata.py", "--weapon", "Karambit", "--skin", "Doppler",
                  "--index-file", index)
        self.assertNotEqual(amb.returncode, 0)
        self.assertIn("paint_index=419", amb.stderr)
        # --paint-index picks exactly one
        out = self.dir / "meta.json"
        r = run("fetch_cs2_metadata.py", "--weapon", "Karambit", "--skin", "Doppler",
                "--paint-index", "419", "--index-file", index, "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(str(json.loads(out.read_text())["paintIndex"]), "419")

    def test_locate_cs2_vpk_returns_not_found_when_absent(self):
        r = run("locate_cs2_vpk.py", "--root", self.dir, "--json")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["found"])

    def test_extract_cs2_textures_falls_back_without_vpk_or_binary(self):
        r = run("extract_cs2_textures.py", "--out", self.dir / "cs2_textures", "--json")
        self.assertEqual(r.returncode, 1)
        result = json.loads(r.stdout)
        self.assertEqual(result["status"], "fallback")
        self.assertIn("no local CS2 VPK", result["reason"])


if __name__ == "__main__":
    unittest.main()
