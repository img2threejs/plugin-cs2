"""Fictional cosmetic-token protocol fixtures; no real assets or renderer authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from cs2_manifest import build_classification_record, build_manifest
from cs2_review import evaluate_knife_review, load_review_scene
from cs2_review_contract import TERMINAL_THRESHOLDS
from test_cs2_manifest import ADMITTED, PROBED, write_png


def metrics():
    return {
        "passId": "fictional-cosmetic-pass", "silhouetteIoU": 0.96,
        "aspectRatioDelta": 0.01, "scaleDelta": 0.01,
        "finishMaterialResponse": 0.9, "identityDetail": 0.9,
        "paintedRegions": [{"id": "color-patch", "score": 0.9, "confidence": 1.0}],
        "criticalFeatures": [{"id": "printed-symbol", "score": 0.9}],
        "projection": {"required": True, "coverage": 0.9},
        "multiAngle": {"degenerate": False, "angles": [{"id": "a"}, {"id": "b"}]},
    }


class PassWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cs2-fictional-pass-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.home = self.workspace / "home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")
        reference = self.workspace / "fictional-token.png"
        write_png(reference)
        classification = build_classification_record("glove", "fictional-cosmetic-token", 0.99,
                                                     ["synthetic-protocol-only"])
        self.manifest = build_manifest(reference, classification, admission_artifact=ADMITTED,
                                       probe_artifact=PROBED)
        self.put("cs2-intake.json", self.manifest)
        self.put("cs2-review-inputs.json", metrics())
        self.scene = {
            "version": 1, "fixtureId": "fictional-cosmetic-policy-v1",
            "reference": "fictional-token.png", "identity": {"family": "glove"},
            "camera": {"projection": "orthographic"}, "transform": {"scale": [1, 1, 1]},
            "environment": {"hash": "synthetic-not-a-render"},
            "resolution": {"width": 128, "height": 128}, "background": "white",
            "rendererVersion": "synthetic-protocol-only",
            "calibration": {"status": "synthetic-no-renderer-authority"},
            "thresholds": dict(TERMINAL_THRESHOLDS),
        }

    def put(self, name, value):
        path = self.workspace / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def run_command(self, command):
        return subprocess.run(shlex.split(command.format(plugin_dir=ROOT)), cwd=self.workspace,
                              env=self.env, capture_output=True, text=True, timeout=30)

    def test_literal_domain_pass_produces_scene_and_refreshes_manifest_camera(self):
        domain = json.loads((ROOT / "domain.json").read_text())
        for position in ([0.0, 0.0, 3.0], [1.0, 0.0, 4.0]):
            with self.subTest(position=position):
                self.manifest["reviewScene"]["camera"]["position"] = position
                self.put("cs2-intake.json", self.manifest)
                for _, command in domain["passSteps"]:
                    result = self.run_command(command)
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                scene = json.loads((self.workspace / "cs2-review-scene.json").read_text())
                report = json.loads((self.workspace / "cs2-review.json").read_text())
                self.assertEqual(scene["camera"]["position"], position)
                self.assertEqual(scene["thresholds"], TERMINAL_THRESHOLDS)
                self.assertEqual(report["verdict"], "pass")
                self.assertEqual(report["reviewScene"]["camera"], scene["camera"])
                self.assertEqual(report["pluginVersion"], json.loads((ROOT / "plugin.json").read_text())["version"])

    def test_scene_producer_refuses_missing_or_invalid_source_without_output(self):
        for invalid in (None, {}, {"version": "unsupported"}):
            with self.subTest(source=invalid):
                self.manifest["reviewScene"] = invalid
                self.put("cs2-intake.json", self.manifest)
                result = self.run_command("python3 {plugin_dir}/tools/cs2_review.py "
                                          "--prepare-scene --manifest cs2-intake.json --out scene.json")
                self.assertEqual(result.returncode, 2)
                envelope = json.loads(result.stdout)
                self.assertTrue(any("reviewScene" in reason for reason in envelope["reasons"]), envelope)
                self.assertFalse((self.workspace / "scene.json").exists())

    def test_lowered_thresholds_cannot_admit_bad_visual_metrics(self):
        self.scene["thresholds"] = {key: 0 for key in TERMINAL_THRESHOLDS}
        bad = metrics()
        bad.update(silhouetteIoU=0.1, aspectRatioDelta=0, scaleDelta=0,
                   finishMaterialResponse=0.1, identityDetail=0.1)
        with self.assertRaisesRegex(ValueError, "threshold"):
            evaluate_knife_review(self.manifest, bad, self.scene, allow_deferrals=True)

    def test_loader_and_direct_evaluation_reject_noncanonical_thresholds(self):
        variants = []
        for value in (0, True, "0.85", None, float("nan"), float("inf")):
            changed = dict(TERMINAL_THRESHOLDS)
            changed["silhouetteIoU"] = value
            variants.append(changed)
        missing = dict(TERMINAL_THRESHOLDS)
        del missing["paintedRegion"]
        variants.extend([missing, dict(TERMINAL_THRESHOLDS, extra=0.8), [], None])
        for thresholds in variants:
            with self.subTest(thresholds=thresholds):
                scene = dict(self.scene, thresholds=thresholds)
                path = self.put("untrusted-scene.json", scene)
                with self.assertRaisesRegex(ValueError, "threshold"):
                    load_review_scene(path)
                with self.assertRaisesRegex(ValueError, "threshold"):
                    evaluate_knife_review(self.manifest, metrics(), scene)

    def test_canonical_policy_preserves_missing_only_deferrals(self):
        inputs = metrics()
        inputs["finishMaterialResponse"] = None
        inputs["deferred"] = {"finishMaterialResponse": "synthetic pass not measured yet"}
        permissive = evaluate_knife_review(self.manifest, inputs, self.scene, allow_deferrals=True)
        self.assertEqual(permissive["verdict"], "pass")
        self.assertEqual(permissive["deferredGates"], ["finishMaterialResponse"])
        strict = evaluate_knife_review(self.manifest, inputs, self.scene)
        self.assertEqual(strict["verdict"], "reject")
        inputs["finishMaterialResponse"] = 0.1
        failed = evaluate_knife_review(self.manifest, inputs, self.scene, allow_deferrals=True)
        self.assertIn("deferral-conflict:finishMaterialResponse", failed["failedGates"])


if __name__ == "__main__":
    unittest.main()
