from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cs2_manifest import build_classification_record, build_manifest, main, persist_manifest, validate_manifest
from cs2_review import evaluate_knife_review, load_review_scene
from cs2_routing import decision_digest
from emit_spec_augmentation import build as build_augmentation
from test_cs2_manifest import ADMITTED, PROBED, write_png


class Cs2RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / "look-alike.png"
        write_png(self.reference)
        self.pin = "a" * 40
        self.candidate = "profile:cs2@" + self.pin
        # Deliberately forge a plausible route. Even its matching digest is NOT
        # proof of identity or base validation; the classifier still has a veto.
        self.decision = {
            "kind": "img2.route-decision", "version": 1, "runId": "fixture", "revision": 1,
            "phase": "decided", "suspendedAt": None,
            "imageSha256": hashlib.sha256(self.reference.read_bytes()).hexdigest(),
            "request": {"expectedOutput": "3d", "intent": [], "explicitRoute": None},
            "inputsDigest": "b" * 64, "inventorySha256": "c" * 64,
            "objects": [{"objectId": "prop", "boxSha256": "d" * 64,
                         "eligible": [self.candidate], "rejected": [], "consultations": [],
                         "decider": "jev:fixture", "status": "resolved", "selected": [self.candidate],
                         "execution": {"mode": "single", "n": 1}}],
            "jevSession": "healthy", "probes": [], "policyVersion": "fixture-v1",
            "versions": {"harness": "fixture", "baseSkill": "fixture", "cards": {}},
            "consentSha256": "e" * 64,
        }
        self.classification = build_classification_record("knife", "talon", 0.98, ["fixture:independent-classification"])

    def manifest(self, classification, **overrides):
        args = {"admission_artifact": ADMITTED, "probe_artifact": PROBED,
                "route_decision": self.decision, "validated_route_sha256": decision_digest(self.decision),
                "object_id": "prop", "resolved_sha": self.pin}
        args.update(overrides)
        return build_manifest(self.reference, classification, **args)

    def test_card_declares_local_augmentation_not_identity(self):
        card = json.loads((ROOT / "route.json").read_text())
        self.assertEqual((card["kind"], card["version"], card["outputKind"]),
                         ("img2.route-card", 1, "spec-augmentation"))
        self.assertEqual(card["costClass"], "local")
        self.assertEqual(card["deps"], [{"probe": "python3>=3.10"}])
        self.assertTrue(all(len(value) <= 600 for value in card["display"].values()))

    def test_route_is_intent_only_missing_classification_still_blocks(self):
        self.decision["identity"] = {"itemFamily": "knife", "confidence": 1.0}
        manifest = self.manifest(None, explicit_identity={"itemFamily": "knife", "name": "CS2"})
        self.assertEqual(manifest["state"], "request-input")
        self.assertNotIn("itemFamily", manifest)
        self.assertNotIn("componentAdapter", manifest)
        self.assertEqual(manifest["identity"]["provenance"], "unknown")
        self.assertEqual(manifest["extensions"]["routeSelection"]["profile"], "cs2")

    def test_matching_forged_route_hash_cannot_override_independent_lookalike(self):
        for negative in ({"isCs2": False}, {"domain": "generic"}, {"kind": "look-alike"}):
            with self.subTest(negative=negative):
                manifest = self.manifest(dict(self.classification, **negative))
                self.assertEqual(manifest["state"], "request-input")
                self.assertNotIn("componentAdapter", manifest)
                self.assertNotIn("itemFamily", manifest)
                self.assertTrue(any("vetoes" in warning for warning in manifest["warnings"]))

    def test_low_confidence_timeout_and_missing_evidence_cannot_be_bypassed(self):
        for patch in ({"confidence": 0.8199}, {"timedOut": True}, {"evidenceRefs": []}, {"provider": ""}):
            with self.subTest(patch=patch):
                self.assertEqual(self.manifest(dict(self.classification, **patch))["state"], "request-input")
        at_floor = self.manifest(dict(self.classification, confidence=0.82))
        self.assertEqual(at_floor["state"], "proceed")

    def test_route_object_image_pin_and_independent_digest_are_required(self):
        for patch in ({"validated_route_sha256": None}, {"validated_route_sha256": "f" * 64},
                      {"object_id": "foreign"}, {"resolved_sha": "f" * 40}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.manifest(self.classification, **patch)
        for mutation in ("image", "phase", "eligibility", "duplicate"):
            with self.subTest(mutation=mutation):
                decision = copy.deepcopy(self.decision)
                if mutation == "image":
                    decision["imageSha256"] = "f" * 64
                elif mutation == "phase":
                    decision["phase"] = "suspended"
                elif mutation == "eligibility":
                    decision["objects"][0]["eligible"] = []
                else:
                    decision["objects"].append(copy.deepcopy(decision["objects"][0]))
                with self.assertRaises(ValueError):
                    self.manifest(self.classification, route_decision=decision,
                                  validated_route_sha256=decision_digest(decision))

    def test_positive_route_preserves_real_classifier_and_legacy_behavior(self):
        routed = self.manifest(self.classification)
        legacy = build_manifest(self.reference, self.classification, admission_artifact=ADMITTED, probe_artifact=PROBED)
        for key in ("classification", "identity", "componentAdapter", "route", "exactnessTier", "assumptions"):
            self.assertEqual(routed[key], legacy[key])
        self.assertEqual(routed["state"], "proceed")
        self.assertEqual(routed["sourceViews"][0]["sha256"], self.decision["imageSha256"])
        self.assertNotIn("routeSelection", legacy["extensions"])
        self.assertEqual(self.manifest(self.classification, admission_artifact={"admitted": False})["state"], "rejected")

    def test_routed_resume_rechecks_changed_classification(self):
        output = self.root / "intake.json"
        persist_manifest(self.manifest(self.classification), output)
        files = {"route.json": self.decision, "classification.json": dict(self.classification, isCs2=False),
                 "admission.json": ADMITTED, "probe.json": PROBED}
        for name, value in files.items():
            (self.root / name).write_text(json.dumps(value))
        with redirect_stdout(StringIO()):
            result = main([str(self.reference), "--resume", "--out", str(output),
                           "--route-decision", str(self.root / "route.json"),
                           "--validated-route-sha256", decision_digest(self.decision),
                           "--resolved-sha", self.pin, "--object-id", "prop",
                           "--classification", str(self.root / "classification.json"),
                           "--admission", str(self.root / "admission.json"), "--probe", str(self.root / "probe.json")])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.read_text())["state"], "request-input")

    def test_forged_proceed_state_cannot_emit_routed_augmentation_or_clear_gate(self):
        manifest = self.manifest(None)
        manifest["state"] = "proceed"
        self.assertFalse(validate_manifest(manifest))
        path = self.root / "forged.json"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "classification"):
            build_augmentation(argparse.Namespace(manifest=path))
        scene = load_review_scene(ROOT / "tests/fixtures/knife_review_scene.json")
        report = evaluate_knife_review(manifest, {}, scene)
        self.assertIn("manifest-state:classification-veto", report["failedGates"])
        self.assertEqual(report["verdict"], "reject")

    def test_routed_selection_cannot_waive_finish_or_identity_detail(self):
        manifest = self.manifest(self.classification)
        metrics = {"silhouetteIoU": 0.99, "aspectRatioDelta": 0.0, "scaleDelta": 0.0,
                   "finishMaterialResponse": 0.1, "identityDetail": 0.1,
                   "paintedRegions": [{"id": "finish", "score": 0.99, "confidence": 1.0}],
                   "criticalFeatures": [{"id": "identity", "score": 0.1}],
                   "projection": {"required": True, "coverage": 0.99},
                   "multiAngle": {"degenerate": False, "angles": [{"id": "a"}, {"id": "b"}]}}
        report = evaluate_knife_review(manifest, metrics, load_review_scene(ROOT / "tests/fixtures/knife_review_scene.json"))
        self.assertEqual(report["verdict"], "reject")
        self.assertTrue({"finishMaterialResponse", "identityDetail", "critical-feature:identity"} <= set(report["failedGates"]))


if __name__ == "__main__":
    unittest.main()
