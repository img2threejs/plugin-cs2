"""Deferral semantics for the cs2-review gate (OpenSpec change `phase-aware-cs2-review`).

Covers: strict-by-default refusal; the closed deferrable set keyed by gate token; the four-cell
truth table (deferred x present/absent x passing/failing); fail-closed handling of unknown or
non-deferrable keys; strict-door non-emptiness for the vacuous arrays; the projection block
precondition; envelope visibility of a deferred pass; the error-envelope CLI paths; the
declaration drift guard; and the regression pinned to the live MP9 run that motivated the change.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import cs2_review  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
SCENE = FIXTURES / "knife_review_scene.json"
LIVE = FIXTURES / "live-mp9"
ORACLE = FIXTURES / "oracle-talon"
CS2_REVIEW = ROOT / "tools" / "cs2_review.py"


def _scene() -> dict:
    return json.loads(SCENE.read_text(encoding="utf-8"))


def _manifest(**overrides) -> dict:
    base = {"state": "proceed", "itemFamily": "knife", "subtype": "karambit", "route": "reference-projection"}
    base.update(overrides)
    return base


def _metrics(**overrides) -> dict:
    """A metrics file that passes every gate in strict mode unless overridden."""
    base = {
        "passId": "material-pass",
        "silhouetteIoU": 0.95,
        "aspectRatioDelta": 0.01,
        "scaleDelta": 0.01,
        "finishMaterialResponse": 0.9,
        "identityDetail": 0.9,
        "paintedRegions": [{"id": "blade", "score": 0.9, "confidence": 0.9}],
        "criticalFeatures": [{"id": "edge", "score": 0.9}],
        "projection": {"required": True, "coverage": 0.9},
        "multiAngle": {"degenerate": False, "angles": [{"id": "a", "azimuth": 0}, {"id": "b", "azimuth": 90}]},
    }
    base.update(overrides)
    return base


def _run(manifest: dict, metrics: dict, *, allow_deferrals: bool) -> dict:
    return cs2_review.evaluate_knife_review(manifest, metrics, _scene(), allow_deferrals=allow_deferrals)


class PerPassDeferralSemantics(unittest.TestCase):
    def test_deferred_absent_metric_defers_the_gate(self):
        metrics = _metrics(finishMaterialResponse=None, deferred={"finishMaterialResponse": "bake not run"})
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["deferredGates"], ["finishMaterialResponse"])
        self.assertEqual(report["deferralCount"], 1)
        self.assertNotIn("finishMaterialResponse", report["failedGates"])

    def test_deferred_missing_key_defers_like_null(self):
        metrics = _metrics(deferred={"identityDetail": "bake not run"})
        del metrics["identityDetail"]
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["deferredGates"], ["identityDetail"])

    def test_null_without_declared_deferral_still_fails(self):
        # The anti-laziness property: prose or omission grants nothing.
        report = _run(_manifest(), _metrics(finishMaterialResponse=None), allow_deferrals=True)
        self.assertEqual(report["verdict"], "reject")
        self.assertIn("finishMaterialResponse", report["failedGates"])

    def test_empty_deferred_map_behaves_as_absent(self):
        report = _run(_manifest(), _metrics(deferred={}), allow_deferrals=True)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["deferredGates"], [])

    def test_all_three_deferrable_gates_deferred_still_evaluates_geometry(self):
        metrics = _metrics(
            finishMaterialResponse=None, identityDetail=None,
            projection={"required": True, "coverage": None},
            deferred={
                "finishMaterialResponse": "bake later",
                "identityDetail": "bake later",
                "projection-coverage": "bake later",
            },
        )
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertEqual(report["failedGates"], [])
        self.assertEqual(len(report["deferredGates"]), 3)
        self.assertEqual(report["verdict"], "pass")
        # Geometry is always evaluated: break it and the same inputs reject.
        metrics["silhouetteIoU"] = None
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "reject")
        self.assertIn("silhouetteIoU", report["failedGates"])


class DeferralVocabularyIsFailClosed(unittest.TestCase):
    def test_non_deferrable_gate_token_is_refused(self):
        report = _run(_manifest(), _metrics(deferred={"silhouetteIoU": "later"}), allow_deferrals=True)
        self.assertIn("deferral-invalid:silhouetteIoU", report["failedGates"])
        self.assertEqual(report["verdict"], "reject")

    def test_typo_key_is_refused_with_the_offending_name(self):
        report = _run(_manifest(), _metrics(deferred={"finishMaterialRespone": "typo"}), allow_deferrals=True)
        self.assertIn("deferral-invalid:finishMaterialRespone", report["failedGates"])

    def test_metric_path_spelling_is_refused(self):
        report = _run(_manifest(), _metrics(deferred={"projection.coverage": "wrong namespace"}), allow_deferrals=True)
        self.assertIn("deferral-invalid:projection.coverage", report["failedGates"])


class DeferralTruthTable(unittest.TestCase):
    def test_deferred_but_present_and_failing_is_a_conflict(self):
        metrics = _metrics(finishMaterialResponse=0.1, deferred={"finishMaterialResponse": "later"})
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "reject")
        self.assertIn("finishMaterialResponse", report["failedGates"])
        self.assertIn("deferral-conflict:finishMaterialResponse", report["failedGates"])

    def test_deferred_but_present_and_passing_is_spurious(self):
        metrics = _metrics(deferred={"identityDetail": "later"})
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "pass")
        self.assertNotIn("identityDetail", report["deferredGates"])
        self.assertEqual(report["spuriousDeferrals"], ["identityDetail"])

    def test_present_junk_value_under_deferral_is_a_conflict_not_a_deferral(self):
        # A present non-numeric value was always a failure; a declared deferral must not launder it.
        metrics = _metrics(finishMaterialResponse="pending", deferred={"finishMaterialResponse": "later"})
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "reject")
        self.assertIn("finishMaterialResponse", report["failedGates"])
        self.assertIn("deferral-conflict:finishMaterialResponse", report["failedGates"])
        self.assertEqual(report["deferredGates"], [])

    def test_inapplicable_projection_deferral_is_recorded_as_spurious(self):
        metrics = _metrics(deferred={"projection-coverage": "later"})
        report = _run(_manifest(route="procedural-finish"), metrics, allow_deferrals=True)
        self.assertIn("projection-coverage", report["spuriousDeferrals"])
        self.assertNotIn("projection-coverage", report["deferredGates"])

    def test_action_mapping_for_deferral_tokens(self):
        # Declaration errors ask for fixed inputs; a conflict is a real quality failure.
        conflict = _run(_manifest(), _metrics(finishMaterialResponse=0.1, deferred={"finishMaterialResponse": "later"}), allow_deferrals=True)
        self.assertEqual(conflict["action"], "refine-code")
        invalid = _run(_manifest(), _metrics(deferred={"silhouetteIoU": "later"}), allow_deferrals=True)
        self.assertEqual(invalid["action"], "request-input")
        refused = _run(_manifest(), _metrics(deferred={"finishMaterialResponse": "later"}), allow_deferrals=False)
        self.assertEqual(refused["action"], "request-input")


class ProjectionDeferralPrecondition(unittest.TestCase):
    def test_omitted_projection_block_is_not_deferrable(self):
        metrics = _metrics(deferred={"projection-coverage": "bake later"})
        del metrics["projection"]
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertIn("projection-evidence-missing", report["failedGates"])
        self.assertEqual(report["verdict"], "reject")

    def test_null_coverage_with_required_true_defers(self):
        metrics = _metrics(
            projection={"required": True, "coverage": None},
            deferred={"projection-coverage": "bake in material-pass"},
        )
        report = _run(_manifest(), metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "pass")
        self.assertIn("projection-coverage", report["deferredGates"])


class StrictModeIsTheDefault(unittest.TestCase):
    def test_a_deferral_request_is_refused_in_strict_mode(self):
        metrics = _metrics(finishMaterialResponse=None, deferred={"finishMaterialResponse": "bake not run"})
        report = _run(_manifest(), metrics, allow_deferrals=False)
        self.assertEqual(report["verdict"], "reject")
        self.assertIn("deferral-refused:finishMaterialResponse", report["failedGates"])
        self.assertIn("finishMaterialResponse", report["failedGates"])
        self.assertEqual(report["deferredGates"], [])
        self.assertEqual(report["mode"], "strict")

    def test_complete_passing_metrics_pass_strict_mode(self):
        report = _run(_manifest(), _metrics(), allow_deferrals=False)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["failedGates"], [])

    def test_empty_painted_regions_fail_the_strict_door(self):
        report = _run(_manifest(), _metrics(paintedRegions=[]), allow_deferrals=False)
        self.assertIn("painted-regions-empty", report["failedGates"])
        self.assertEqual(report["verdict"], "reject")

    def test_empty_critical_features_fail_the_strict_door(self):
        report = _run(_manifest(), _metrics(criticalFeatures=[]), allow_deferrals=False)
        self.assertIn("critical-features-empty", report["failedGates"])

    def test_empty_arrays_keep_previous_behavior_in_allow_deferrals_mode(self):
        report = _run(_manifest(), _metrics(paintedRegions=[], criticalFeatures=[]), allow_deferrals=True)
        self.assertEqual(report["verdict"], "pass")


class ReportIsSelfDescribing(unittest.TestCase):
    def test_clean_strict_report_carries_the_provenance_block(self):
        report = _run(_manifest(), _metrics(), allow_deferrals=False)
        self.assertEqual(report["deferredGates"], [])
        self.assertEqual(report["deferralCount"], 0)
        self.assertEqual(report["spuriousDeferrals"], [])
        self.assertEqual(report["mode"], "strict")
        self.assertEqual(report["passId"], "material-pass")
        self.assertTrue(report["pluginVersion"])


class DeferredMapShapeIsHardValidated(unittest.TestCase):
    def test_non_object_deferred_is_a_structural_error(self):
        with self.assertRaises(ValueError):
            cs2_review._load_deferrals({"deferred": ["finishMaterialResponse"]})

    def test_non_string_reason_is_a_structural_error(self):
        with self.assertRaises(ValueError):
            cs2_review._load_deferrals({"deferred": {"finishMaterialResponse": 3}})

    def test_over_length_reason_is_refused_never_truncated(self):
        with self.assertRaises(ValueError) as ctx:
            cs2_review._load_deferrals({"deferred": {"finishMaterialResponse": "x" * 201}})
        self.assertIn("never truncated", str(ctx.exception))


class LiveRunRegression(unittest.TestCase):
    """Pinned to the run that motivated the change: MP9 'Wild Lily', form-refinement pass, three
    bake-dependent metrics null with prose-only justification, geometry passing."""

    def _live(self):
        manifest = json.loads((LIVE / "cs2-intake.json").read_text(encoding="utf-8"))
        metrics = json.loads((LIVE / "cs2-review-inputs.json").read_text(encoding="utf-8"))
        return manifest, metrics

    def test_prose_only_deferral_still_rejects(self):
        manifest, metrics = self._live()
        report = _run(manifest, metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "reject")
        for token in ("finishMaterialResponse", "identityDetail", "projection-coverage"):
            self.assertIn(token, report["failedGates"])

    def test_declared_deferrals_pass_the_live_inputs(self):
        manifest, metrics = self._live()
        metrics["deferred"] = {
            "finishMaterialResponse": "bake not yet run; lands in material-pass",
            "identityDetail": "bake not yet run; lands in material-pass",
            "projection-coverage": "bake not yet run; lands in material-pass",
        }
        report = _run(manifest, metrics, allow_deferrals=True)
        self.assertEqual(report["verdict"], "pass", report["failedGates"])
        self.assertEqual(report["failedGates"], [])
        self.assertEqual(
            sorted(report["deferredGates"]),
            ["finishMaterialResponse", "identityDetail", "projection-coverage"],
        )
        self.assertEqual(report["passId"], "form-refinement")

    def test_the_same_declared_deferrals_reject_in_strict_mode(self):
        manifest, metrics = self._live()
        metrics["deferred"] = {"finishMaterialResponse": "bake not yet run"}
        report = _run(manifest, metrics, allow_deferrals=False)
        self.assertEqual(report["verdict"], "reject")
        self.assertIn("deferral-refused:finishMaterialResponse", report["failedGates"])


class EnvelopeAndCli(unittest.TestCase):
    def _cli(self, metrics: dict, *args: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            metrics_path = Path(tmp) / "metrics.json"
            out_path = Path(tmp) / "report.json"
            manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
            metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(CS2_REVIEW), "--manifest", str(manifest_path),
                 "--metrics", str(metrics_path), "--out", str(out_path), *args],
                capture_output=True, text=True,
            )
            proc.report = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else None
            return proc

    def test_deferred_pass_prints_one_envelope_naming_the_deferral(self):
        metrics = _metrics(finishMaterialResponse=None, deferred={"finishMaterialResponse": "bake later"})
        proc = self._cli(metrics, "--allow-deferrals")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["kind"], "img2.gate-verdict")
        self.assertEqual(envelope["status"], "pass")
        self.assertEqual(envelope["reasons"], ["deferred: finishMaterialResponse"])
        self.assertEqual(envelope["evidence"]["deferredGates"], ["finishMaterialResponse"])
        self.assertEqual(envelope["evidence"]["mode"], "allow-deferrals")

    def test_help_still_exits_zero(self):
        # Regression: an over-broad SystemExit catch once turned --help's exit 0 into 2.
        proc = subprocess.run([sys.executable, str(CS2_REVIEW), "--help"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--allow-deferrals", proc.stdout)

    def test_unknown_flag_emits_an_error_envelope_before_exit_2(self):
        proc = self._cli(_metrics(), "--terminal")
        self.assertEqual(proc.returncode, 2)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["status"], "error")
        self.assertTrue(any("--terminal" in reason for reason in envelope["reasons"]), envelope)

    def test_missing_metrics_file_names_the_file_in_an_error_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(CS2_REVIEW), "--manifest", str(manifest_path),
                 "--metrics", str(Path(tmp) / "absent.json"), "--out", str(Path(tmp) / "r.json")],
                capture_output=True, text=True,
            )
        self.assertEqual(proc.returncode, 2)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["status"], "error")
        self.assertTrue(any("absent.json" in reason for reason in envelope["reasons"]))

    def test_malformed_deferred_shape_is_a_structural_error_via_cli(self):
        proc = self._cli(_metrics(deferred="finishMaterialResponse"), "--allow-deferrals")
        self.assertEqual(proc.returncode, 2)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["status"], "error")


class DeclarationDriftGuard(unittest.TestCase):
    """gates.json is the strict door and must never carry the leniency flag; domain.json's
    per-pass row must. Same shape as the base's gateRunnerArgv parity guard: a copy-paste between
    the two files turns the suite red instead of silently disarming the final door."""

    def test_gates_json_is_strict_and_domain_json_opts_into_leniency(self):
        gates = json.loads((ROOT / "gates.json").read_text(encoding="utf-8"))
        domain = json.loads((ROOT / "domain.json").read_text(encoding="utf-8"))
        gate_cmd = next(row["command"] for row in gates if row["id"] == "cs2-review")
        pass_cmd = next(cmd for step_id, cmd in domain["passSteps"] if step_id == "cs2-review")
        self.assertNotIn("--allow-deferrals", gate_cmd)
        self.assertIn("--allow-deferrals", pass_cmd)


if __name__ == "__main__":
    unittest.main()
