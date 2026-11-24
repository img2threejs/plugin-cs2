#!/usr/bin/env python3
"""Run the fixture-independent subset; never claim the historical/full gate passed."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    "test_cs2_foundation",
    "test_cs2_manifest",
    "test_cs2_spec_template",
    "test_cs2_asset_tools",
    "test_cs2_pixels",
    "test_cs2_measure",
    "test_cs2_terminal",
    "test_cs2_pass_workflow",
    "test_cs2_review_deferrals.DeferredMapShapeIsHardValidated",
    "test_cs2_review_deferrals.DeclarationDriftGuard",
    "test_cs2_review_deferrals.EnvelopeAndCli.test_help_still_exits_zero",
    "test_cs2_review_deferrals.EnvelopeAndCli.test_unknown_flag_emits_an_error_envelope_before_exit_2",
    "test_cs2_review_deferrals.EnvelopeAndCli.test_missing_metrics_file_names_the_file_in_an_error_envelope",
    "test_cs2_routing.Cs2RoutingTests.test_card_declares_local_augmentation_not_identity",
    "test_cs2_routing.Cs2RoutingTests.test_route_is_intent_only_missing_classification_still_blocks",
    "test_cs2_routing.Cs2RoutingTests.test_matching_forged_route_hash_cannot_override_independent_lookalike",
    "test_cs2_routing.Cs2RoutingTests.test_low_confidence_timeout_and_missing_evidence_cannot_be_bypassed",
    "test_cs2_routing.Cs2RoutingTests.test_route_object_image_pin_and_independent_digest_are_required",
    "test_cs2_routing.Cs2RoutingTests.test_positive_route_preserves_real_classifier_and_legacy_behavior",
    "test_cs2_routing.Cs2RoutingTests.test_routed_resume_rechecks_changed_classification",
]


def main():
    with tempfile.TemporaryDirectory(prefix="cs2-synthetic-suite-") as temporary:
        root = Path(temporary)
        source = root / "source"
        (source / "tools").mkdir(parents=True)
        (source / "tests").mkdir()
        for path in (ROOT / "tools").glob("*.py"):
            shutil.copy2(path, source / "tools" / path.name)
        for module in {target.split(".")[0] for target in TARGETS}:
            shutil.copy2(ROOT / "tests" / (module + ".py"), source / "tests" / (module + ".py"))
        for name in ("plugin.json", "domain.json", "gates.json", "route.json"):
            shutil.copy2(ROOT / name, source / name)
        home = root / "home"
        home.mkdir()
        environment = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1", PYTHONPATH="tests")
        print("Synthetic-only subset: original historical/shared-scene and full-discovery gates remain unverified.", flush=True)
        print("Snapshot excludes tests/fixtures; HOME is an empty disposable directory.", flush=True)
        return subprocess.run([sys.executable, "-m", "unittest", "-v", *TARGETS],
                              cwd=source, env=environment, timeout=1200).returncode


if __name__ == "__main__":
    raise SystemExit(main())
