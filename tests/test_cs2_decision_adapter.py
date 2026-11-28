from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cs2_decision_adapter import build_snapshot
from cs2_manifest import build_classification_record, build_manifest
from cs2_review import evaluate_knife_review
from test_cs2_manifest import ADMITTED, PROBED, write_png


class Cs2DecisionAdapterTests(unittest.TestCase):
    """Synthetic protocol inputs only; these do not measure rendered quality."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings = []
        reference = self.root / "reference.png"
        write_png(reference)
        self.bind("reference", "reference.png")
        classification = build_classification_record("knife", "talon", 0.98, ["fixture:classification"])
        self.manifest = build_manifest(reference, classification, route="procedural-finish",
                                       admission_artifact=ADMITTED, probe_artifact=PROBED)
        self.json_file("manifest", "manifest.json", self.manifest)
        self.spec = {"componentTree": [{"id": "root"}, {"id": "blade", "geometry": {"profile": [1, 2]},
                                                                       "material": {"roughness": 0.6}}],
                     "featureTargets": [{"id": "cs2-finish", "tier": "critical", "mustPass": True}]}
        self.json_file("spec", "spec.json", self.spec)
        self.json_file("critical-features", "critical-features.json", self.spec["featureTargets"])
        self.metrics = {"passId": "material-pass", "silhouetteIoU": 0.99,
                        "aspectRatioDelta": 0.0, "scaleDelta": 0.0,
                        "finishMaterialResponse": 0.99, "identityDetail": 0.99,
                        "paintedRegions": [{"id": "finish", "score": 0.99, "confidence": 1.0}],
                        "criticalFeatures": [{"id": "cs2-finish", "score": 0.99}],
                        "multiAngle": {"degenerate": False, "angles": [{"id": "orbit-a"}, {"id": "orbit-b"}]}}
        self.scene = json.loads((ROOT / "tests/fixtures/knife_review_scene.json").read_text())
        self.json_file("metrics", "metrics.json", self.metrics)
        self.json_file("review-scene", "scene.json", self.scene)
        self.refresh_gate()
        self.json_file("camera", "camera.json", {"fixture": "synthetic camera; no runtime measurement claim"})
        (self.root / "source.js").write_text("// synthetic source bytes for evidence binding\n")
        self.bind("source", "source.js")
        for role in ("render", "view-front", "view-orbit-a", "view-orbit-b"):
            write_png(self.root / (role + ".png"))
            self.bind(role, role + ".png")

    def bind(self, role, path):
        self.bindings = [binding for binding in self.bindings if binding["role"] != role]
        self.bindings.append({"role": role, "path": path,
                              "sha256": hashlib.sha256((self.root / path).read_bytes()).hexdigest()})

    def json_file(self, role, path, value):
        (self.root / path).write_text(json.dumps(value))
        self.bind(role, path)

    def refresh_gate(self):
        self.json_file("gate", "gate.json", evaluate_knife_review(self.manifest, self.metrics, self.scene))

    def snapshot(self, group="quality-review", **kwargs):
        return build_snapshot(self.root, group, self.bindings, pass_id="material-pass", **kwargs)

    def concrete_input(self, *, repair=False, material=False):
        proposal = copy.deepcopy(self.spec)
        sources = []
        if material:
            proposal["componentTree"][1]["material"]["roughness"] = 0.4
            write_png(self.root / "material-source.png")
            self.bind("material-source", "material-source.png")
            sources = [next(b["sha256"] for b in self.bindings if b["role"] == "material-source")]
            fields, operations = ["material.roughness"], ["adjust-material"]
        else:
            proposal["componentTree"][1]["geometry"]["profile"] = [1, 3]
            fields, operations = ["geometry.profile"], ["refine-profile"]
        self.json_file("proposal-cs2-profile", "proposal.json", proposal)
        plan = {"id": "cs2-profile", "passId": "material-pass", "components": ["blade"],
                "operations": operations, "fieldPaths": fields, "materialSources": sources,
                "dependencies": [], "rigHandoff": False}
        # Explicit synthetic trusted-code scope, not a permission inferred from
        # the fixture's names, candidate metadata or source hash.
        scope = {"pass_id": "material-pass", "pass_unlocked": True, "components": ["blade"],
                 "operations": operations, "field_paths": fields, "authorized_sources": list(sources),
                 "available_dependencies": [], "rig_required": False, "rig_available": False}
        if repair:
            scope["permissions"] = ["write-spec"]
        return {"plans": [plan], "scope": scope, "proposalRoles": {"cs2-profile": "proposal-cs2-profile"}}

    def test_snapshot_preserves_hashes_and_strict_gate_without_claiming_acceptance(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["bindings"], self.bindings)
        self.assertEqual(snapshot["gate"]["mode"], "strict")
        self.assertEqual(snapshot["authority"], "advisory-input-only")
        self.assertEqual(snapshot["candidates"], [])
        self.assertEqual(snapshot["requirements"]["criticalFeatures"], [{"id": "cs2-finish", "threshold": 3}])
        self.assertNotIn(str(self.root), json.dumps(snapshot["observations"]))

    def test_changed_source_and_render_hashes_are_refused(self):
        for role in ("source", "render"):
            with self.subTest(role=role):
                binding = next(item for item in self.bindings if item["role"] == role)
                path = self.root / binding["path"]
                old = path.read_bytes()
                path.write_bytes(old + b"changed")
                with self.assertRaisesRegex(ValueError, "stale evidence"):
                    self.snapshot()
                path.write_bytes(old)

    def test_gate_recalculation_refuses_edited_report_even_with_updated_hash(self):
        report = json.loads((self.root / "gate.json").read_text())
        report["metrics"]["identityDetail"] = 0.1
        self.json_file("gate", "gate.json", report)
        with self.assertRaisesRegex(ValueError, "gate report is stale"):
            self.snapshot()

    def test_missing_views_reference_mismatch_and_cross_pass_are_refused(self):
        original = copy.deepcopy(self.bindings)
        self.bindings = [item for item in original if item["role"] != "view-orbit-b"]
        with self.assertRaisesRegex(ValueError, "missing evidence roles"):
            self.snapshot()
        self.bindings = original
        self.manifest["sourceViews"][0]["sha256"] = "f" * 64
        self.json_file("manifest", "manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "reference does not match"):
            self.snapshot()
        self.manifest["sourceViews"][0]["sha256"] = hashlib.sha256((self.root / "reference.png").read_bytes()).hexdigest()
        self.json_file("manifest", "manifest.json", self.manifest)
        self.metrics["passId"] = "foreign-pass"
        self.json_file("metrics", "metrics.json", self.metrics)
        with self.assertRaisesRegex(ValueError, "another pass"):
            self.snapshot()

    def test_unsafe_paths_symlinks_duplicate_roles_and_missing_classification_fail(self):
        original = copy.deepcopy(self.bindings)
        self.bindings[0]["path"] = "../escape.png"
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.snapshot()
        self.bindings = copy.deepcopy(original)
        (self.root / "link.png").symlink_to(self.root / "reference.png")
        self.bindings[0]["path"] = "link.png"
        with self.assertRaises((OSError, ValueError)):
            self.snapshot()
        self.bindings = original + [copy.deepcopy(original[0])]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.snapshot()
        self.bindings = original
        del self.manifest["classification"]
        self.json_file("manifest", "manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "classification"):
            self.snapshot()

    def test_strategy_uses_exact_shared_shape_only_with_bound_concrete_proposal_and_scope(self):
        self.assertEqual(self.snapshot("build-strategy", unlocked=True)["candidates"], [])
        supplied = self.concrete_input()
        self.assertEqual(self.snapshot("build-strategy", plan_input=supplied)["candidates"], [])
        candidates = self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"]
        self.assertEqual(candidates, supplied["plans"])
        self.assertEqual(set(candidates[0]), {"id", "passId", "components", "operations", "fieldPaths",
                                            "materialSources", "dependencies", "rigHandoff"})
        self.assertEqual(candidates[0]["fieldPaths"], ["geometry.profile"])
        self.assertNotIn("argv", candidates[0])
        self.bindings = [b for b in self.bindings if b["role"] != "proposal-cs2-profile"]
        self.assertEqual(self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"], [])

    def test_material_sources_must_be_actual_bound_independently_authorized_sha256(self):
        supplied = self.concrete_input(material=True)
        candidates = self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"]
        self.assertEqual(candidates, supplied["plans"])
        digest = candidates[0]["materialSources"][0]
        self.assertEqual(digest, hashlib.sha256((self.root / "material-source.png").read_bytes()).hexdigest())
        supplied["scope"]["authorized_sources"] = []
        self.assertEqual(self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"], [])
        supplied["scope"]["authorized_sources"] = ["f" * 64]
        supplied["plans"][0]["materialSources"] = ["f" * 64]
        self.assertEqual(self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"], [])
        supplied["plans"][0]["materialSources"] = []
        self.assertEqual(self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"], [])

    def test_noop_global_route_camera_and_protected_changes_are_not_executable_plans(self):
        supplied = self.concrete_input()
        for change in ("noop", "route", "camera", "component", "protected"):
            with self.subTest(change=change):
                proposal = copy.deepcopy(self.spec)
                if change != "noop":
                    proposal["componentTree"][1]["geometry"]["profile"] = [1, 3]
                if change == "route":
                    proposal["cs2Intake"] = {"route": "procedural-finish"}
                elif change == "camera":
                    proposal["referenceCamera"] = {"position": [1, 2, 3]}
                elif change == "component":
                    proposal["componentTree"].append({"id": "foreign"})
                elif change == "protected":
                    proposal["componentTree"][1]["geometry"]["profile"] = {"threshold": 0}
                self.json_file("proposal-cs2-profile", "proposal.json", proposal)
                self.assertEqual(self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"], [])

    def test_unavailable_operations_dependencies_components_and_scope_are_filtered(self):
        for patch in ({"operations": ["unknown"]}, {"dependencies": ["unavailable"]},
                      {"components": ["root"]}, {"fieldPaths": ["geometry.segments"]}, {"passId": "foreign-pass"}):
            with self.subTest(patch=patch):
                supplied = self.concrete_input()
                supplied["plans"][0].update(patch)
                self.assertEqual(self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"], [])
        supplied = self.concrete_input()
        supplied["scope"]["rig_required"] = True
        self.assertEqual(self.snapshot("build-strategy", unlocked=True, plan_input=supplied)["candidates"], [])
        supplied = self.concrete_input()
        supplied["plans"][0]["componentIds"] = ["blade"]
        with self.assertRaisesRegex(ValueError, "shared plan shape"):
            self.snapshot("build-strategy", unlocked=True, plan_input=supplied)

    def test_concrete_plan_cannot_override_independent_classifier(self):
        supplied = self.concrete_input()
        self.manifest["classification"]["isCs2"] = False
        self.json_file("manifest", "manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "vetoes CS2"):
            self.snapshot("build-strategy", unlocked=True, plan_input=supplied)

    def test_repair_wraps_concrete_plan_without_inventing_permissions_or_input_placeholder(self):
        with self.assertRaisesRegex(ValueError, "fresh failed gate"):
            self.snapshot("repair", unlocked=True)
        self.metrics["silhouetteIoU"] = 0.1
        self.json_file("metrics", "metrics.json", self.metrics)
        self.refresh_gate()
        self.assertEqual(self.snapshot("repair", unlocked=True)["candidates"], [])
        supplied = self.concrete_input(repair=True)
        self.assertEqual(self.snapshot("repair", plan_input=supplied)["candidates"], [])
        candidate = self.snapshot("repair", unlocked=True, plan_input=supplied)["candidates"][0]
        self.assertEqual(set(candidate), {"id", "hypothesis", "action", "plan", "permissions"})
        self.assertEqual(candidate["plan"], supplied["plans"][0])
        self.assertEqual(candidate["id"], candidate["plan"]["id"])
        self.assertEqual(candidate["hypothesis"], "geometry")
        self.assertEqual(candidate["permissions"], ["write-spec"])
        self.assertEqual(self.snapshot("repair", unlocked=True, plan_input=supplied)["gate"]["verdict"], "reject")
        supplied["scope"]["permissions"] = []
        self.assertEqual(self.snapshot("repair", unlocked=True, plan_input=supplied)["candidates"], [])

    def test_matching_report_cannot_launder_lowered_gate_thresholds(self):
        self.metrics["silhouetteIoU"] = 0.1
        self.json_file("metrics", "metrics.json", self.metrics)
        self.refresh_gate()
        report = json.loads((self.root / "gate.json").read_text())
        self.assertEqual(report["verdict"], "reject")
        self.assertEqual(report["failedGates"], ["silhouetteIoU"])
        self.scene["thresholds"]["silhouetteIoU"] = 0.01
        self.json_file("review-scene", "scene.json", self.scene)
        with self.assertRaisesRegex(ValueError, "frozen terminal policy"):
            self.refresh_gate()
        # An attacker can still hand-edit a matching passing report for the
        # lowered floor, with fresh hashes and the same below-policy metrics.
        report.update({"verdict": "pass", "action": "continue", "failedGates": []})
        self.json_file("gate", "gate.json", report)
        with self.assertRaisesRegex(ValueError, "frozen CS2 gate thresholds"):
            self.snapshot()


if __name__ == "__main__":
    unittest.main()
