from __future__ import annotations

import argparse
import functools
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from cs2_review_contract import TERMINAL_THRESHOLDS, validate_terminal_thresholds

REQUIRED_SCENE_KEYS = {
    "version",
    "fixtureId",
    "reference",
    "identity",
    "camera",
    "transform",
    "environment",
    "resolution",
    "background",
    "rendererVersion",
    "calibration",
    "thresholds",
}

# The closed deferrable set: the gates whose metrics are produced by the projection bake and so
# cannot exist in passes before material-pass. Hardcoded HERE, never read from the scene fixture --
# --scene is a caller-supplied path, and a safety parameter must not live in swappable input
# (design D3). Keys are gate tokens, the same vocabulary failedGates uses. Geometry and orbit
# gates are never deferrable: renders exist in every pass, so a report can never be produced with
# zero evaluated gates.
DEFERRABLE_GATES = ("finishMaterialResponse", "identityDetail", "projection-coverage")
MAX_DEFERRAL_REASON_CHARS = 200


@functools.lru_cache(maxsize=1)
def _plugin_version() -> str:
    # Read lazily, not at import: this is a blocking-gate binary, and a missing or corrupted
    # plugin.json must surface as an error ENVELOPE from main(), never as a bare import-time
    # traceback the gate runner can only report as opaque.
    manifest = json.loads(
        (Path(__file__).resolve().parent.parent / "plugin.json").read_text(encoding="utf-8")
    )
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version:
        raise ValueError('plugin.json has no string "version"')
    return version


def load_review_scene(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("review scene must be a JSON object")
    missing = REQUIRED_SCENE_KEYS - payload.keys()
    if missing:
        raise ValueError("review scene is missing: " + ", ".join(sorted(missing)))
    validate_terminal_thresholds(payload.get("thresholds"))
    if payload.get("version") != 1:
        raise ValueError("unsupported review scene version")
    return payload


def _pass_scene(manifest: dict[str, Any]) -> dict[str, Any]:
    from cs2_manifest import validate_manifest
    from cs2_review_contract import validate_review_scene

    if not validate_manifest(manifest) or manifest.get("state") != "proceed":
        raise ValueError("reviewScene requires a valid, admitted CS2 manifest")
    source = manifest.get("reviewScene")
    if not isinstance(source, dict) or not isinstance(source.get("orbitViewpoints"), list):
        raise ValueError("manifest reviewScene is missing or invalid")
    errors = validate_review_scene(source)
    if errors:
        raise ValueError("manifest reviewScene: " + "; ".join(errors))
    if (any(not isinstance(source.get(key), dict) or not source[key]
            for key in ("camera", "objectTransform"))
            or not isinstance(source.get("resolution"), list) or len(source["resolution"]) != 2):
        raise ValueError("manifest reviewScene camera, transform or resolution is invalid")
    views = manifest.get("sourceViews")
    if not views or not isinstance(views[0], dict) or not views[0].get("path"):
        raise ValueError("manifest reviewScene requires a declared reference")
    return {
        "version": 1, "fixtureId": "manifest-per-pass-v1", "reference": views[0]["path"],
        "identity": {"family": manifest.get("itemFamily"), "subtype": manifest.get("subtype")},
        "camera": source["camera"], "transform": source["objectTransform"],
        "environment": {"hash": source["environmentHash"], "exposure": source["exposure"],
                        "toneMapping": source["toneMapping"]},
        "resolution": {"width": source["resolution"][0], "height": source["resolution"][1]},
        "background": source["background"], "rendererVersion": source["rendererVersion"],
        "calibration": {"status": "manifest-policy-only-not-authenticated-renderer-evidence"},
        "thresholds": dict(TERMINAL_THRESHOLDS),
    }


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _failed_threshold(metrics: dict[str, Any], key: str, threshold: float, *, maximum: bool) -> bool:
    value = metrics.get(key)
    if not _number(value):
        return True
    return float(value) > threshold if maximum else float(value) < threshold


def _metric_state(value: Any, threshold: float, *, maximum: bool = False) -> str:
    """"missing" | "failing" | "passing" -- the split _failed_threshold collapses. Deferral
    semantics need to tell a metric that does not exist yet from one that exists and fails: only
    the former is deferrable, and the latter under a declared deferral is a producer contradiction
    (deferral-conflict). A PRESENT non-numeric value is "failing", not "missing" -- junk was always
    a failure, and a declared deferral must not launder it into a clean deferral."""
    if value is None:
        return "missing"
    if not _number(value):
        return "failing"
    failed = float(value) > threshold if maximum else float(value) < threshold
    return "failing" if failed else "passing"


def _load_deferrals(inputs: dict[str, Any]) -> dict[str, str]:
    """Validate the metrics file's `deferred` object shape. Shape violations are structural
    errors (exit 2), not gate failures: a malformed map means the producer's intent is unreadable.
    Over-length reasons are refused, never truncated -- a truncated justification is a worse audit
    artifact than a refusal."""
    raw = inputs.get("deferred")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError('metrics "deferred" must be an object mapping gate token to reason string')
    for key, reason in raw.items():
        if not isinstance(reason, str):
            raise ValueError(f'deferred[{key!r}] must be a plain string reason')
        if len(reason) > MAX_DEFERRAL_REASON_CHARS:
            raise ValueError(
                f'deferred[{key!r}] reason is {len(reason)} characters; the limit is '
                f'{MAX_DEFERRAL_REASON_CHARS} and it is never truncated'
            )
    return dict(raw)


def _region_results(inputs: dict[str, Any], threshold: float, *, strict: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    raw = inputs.get("paintedRegions", [])
    if not isinstance(raw, list):
        return [], ["painted-regions-invalid"]
    if strict and not raw:
        # The strict door's teeth: an empty list iterated zero times and passed this gate outright
        # at every door. A CS2 skin is a paint job; non-emptiness is unconditional (design D7).
        return [], ["painted-regions-empty"]
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for region in raw:
        if not isinstance(region, dict) or not isinstance(region.get("id"), str):
            failures.append("painted-region-invalid")
            continue
        score = region.get("score")
        confidence = region.get("confidence")
        result = {"id": region["id"], "score": score, "confidence": confidence}
        results.append(result)
        if not _number(score) or float(score) < threshold:
            failures.append(f"painted-region:{region['id']}")
        if not _number(confidence):
            failures.append(f"painted-region-confidence:{region['id']}")
    return results, failures


def _critical_feature_failures(inputs: dict[str, Any], default_threshold: float, *, strict: bool = False) -> list[str]:
    raw = inputs.get("criticalFeatures", [])
    if not isinstance(raw, list):
        return ["critical-features-invalid"]
    if strict and not raw:
        return ["critical-features-empty"]
    failures: list[str] = []
    for feature in raw:
        if not isinstance(feature, dict) or not isinstance(feature.get("id"), str):
            failures.append("critical-feature-invalid")
            continue
        threshold = feature.get("threshold", default_threshold)
        if not _number(feature.get("score")) or not _number(threshold):
            failures.append(f"critical-feature:{feature['id']}")
        elif float(feature["score"]) < float(threshold):
            failures.append(f"critical-feature:{feature['id']}")
    return failures


def evaluate_knife_review(
    manifest: dict[str, Any],
    inputs: dict[str, Any],
    review_scene: dict[str, Any],
    *,
    allow_deferrals: bool = False,
) -> dict[str, Any]:
    validate_terminal_thresholds(review_scene.get("thresholds"))
    thresholds = review_scene["thresholds"]
    deferrals = _load_deferrals(inputs)
    failed: list[str] = []
    deferred_gates: list[str] = []
    spurious_deferrals: list[str] = []
    family = manifest.get("itemFamily")
    # No family gate. Every threshold below is about the surface and the silhouette -- finish
    # response, painted-region coverage, identity detail -- and those apply to a rifle skin exactly
    # as they do to a knife. Requiring the knife adapter here would have failed the review for any
    # item whose geometry the agent inferred, which is the case this plugin now serves.
    if manifest.get("state") != "proceed":
        failed.append(f"manifest-state:{manifest.get('state', 'missing')}")
    if manifest.get("extensions", {}).get("routeSelection"):
        # A matching route hash cannot launder a missing/negative classification.
        from cs2_manifest import _classification_error
        if _classification_error(manifest.get("classification")):
            failed.append("manifest-state:classification-veto")

    # Strict is the default: a deferral request is itself refused, and an unknown or
    # non-deferrable key is a named failure in either mode -- a typo must not defer nothing while
    # the producer believes it deferred something (fail closed, design D1/D2).
    if not allow_deferrals:
        for token in sorted(deferrals):
            failed.append(f"deferral-refused:{token}")
    else:
        for token in sorted(deferrals):
            if token not in DEFERRABLE_GATES:
                failed.append(f"deferral-invalid:{token}")

    def honored(token: str) -> bool:
        return allow_deferrals and token in deferrals and token in DEFERRABLE_GATES

    def judge(token: str, state: str) -> None:
        # The one definition of the deferral truth table (design D4); every deferrable gate routes
        # through here so the cells cannot drift apart between call sites.
        if state == "missing":
            if honored(token):
                deferred_gates.append(token)
            else:
                failed.append(token)
        elif state == "failing":
            failed.append(token)
            if honored(token):
                failed.append(f"deferral-conflict:{token}")
        elif honored(token):
            spurious_deferrals.append(token)

    for key in ("silhouetteIoU", "aspectRatioDelta", "scaleDelta"):
        maximum = key != "silhouetteIoU"
        if _failed_threshold(inputs, key, float(thresholds[key]), maximum=maximum):
            failed.append(key)
    for key in ("finishMaterialResponse", "identityDetail"):
        judge(key, _metric_state(inputs.get(key), float(thresholds[key])))

    strict = not allow_deferrals
    region_results, region_failures = _region_results(inputs, float(thresholds["paintedRegion"]), strict=strict)
    failed.extend(region_failures)
    failed.extend(_critical_feature_failures(inputs, float(thresholds["identityDetail"]), strict=strict))

    projection = inputs.get("projection")
    if manifest.get("route") == "reference-projection":
        if not isinstance(projection, dict) or projection.get("required") is not True:
            # Not deferrable, even under a declared projection-coverage deferral: deferring the
            # coverage number still requires declaring the projection obligation itself.
            failed.append("projection-evidence-missing")
        else:
            judge("projection-coverage", _metric_state(projection.get("coverage"), float(thresholds["projectionCoverage"])))
    if honored("projection-coverage") and not (
        "projection-coverage" in deferred_gates
        or "projection-coverage" in spurious_deferrals
        or "deferral-conflict:projection-coverage" in failed
    ):
        # Declared but never judged (non-projection route, or projection-evidence-missing fired):
        # recorded as spurious so a producer never believes it deferred something that deferred
        # nothing (design D2).
        spurious_deferrals.append("projection-coverage")

    multi_angle = inputs.get("multiAngle")
    if not isinstance(multi_angle, dict) or multi_angle.get("degenerate") is True:
        failed.append("degenerate-orbit")
    elif len(multi_angle.get("angles", [])) < 2:
        failed.append("orbit-coverage-missing")

    notes = manifest.get("approximationNotes", inputs.get("approximationNotes", []))
    approximation_notes = [str(note) for note in notes] if isinstance(notes, list) else []
    hidden_confidence = manifest.get("confidence", {}).get("hiddenRegions")
    report = {
        "verdict": "pass" if not failed else "reject",
        "action": "continue" if not failed else ("request-input" if any(
            # deferral-refused / deferral-invalid are declaration errors the producer must fix in
            # its inputs; deferral-conflict is deliberately NOT here -- the metric is present and
            # failing, a real quality failure that routes to refine-code like any other.
            item.startswith(("manifest-state", "projection-evidence", "orbit-coverage", "deferral-refused", "deferral-invalid"))
            for item in failed
        ) else "refine-code"),
        "family": family,
        "subtype": manifest.get("subtype"),
        "exactnessTier": manifest.get("exactnessTier"),
        "route": manifest.get("route"),
        "reviewScene": {
            "version": review_scene["version"],
            "fixtureId": review_scene["fixtureId"],
            "camera": review_scene["camera"],
            "transform": review_scene["transform"],
            "environment": review_scene["environment"],
            "resolution": review_scene["resolution"],
            "background": review_scene["background"],
            "rendererVersion": review_scene["rendererVersion"],
            "calibration": review_scene["calibration"],
        },
        "metrics": inputs,
        "paintedRegions": region_results,
        "perRegionConfidence": {region["id"]: region["confidence"] for region in region_results},
        "hiddenRegionConfidence": hidden_confidence,
        "approximationNotes": approximation_notes,
        "failedGates": failed,
        # Provenance block (design D6): mode makes the shared --out path self-describing when the
        # terminal gate never runs; passId is echoed once, top-level; pluginVersion records which
        # rules judged this pass. deferredGates is ALWAYS present -- an empty array is the "zero
        # deferrals" signal, distinct from "written by an older tool".
        "mode": "allow-deferrals" if allow_deferrals else "strict",
        "passId": inputs.get("passId"),
        "pluginVersion": _plugin_version(),
        "deferredGates": deferred_gates,
        "deferralCount": len(deferred_gates),
        "spuriousDeferrals": spurious_deferrals,
    }
    return report


def _load_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# stdout carries exactly one img2.gate-verdict envelope and nothing else: the gate runner parses
# the WHOLE stream as a single JSON document (PLUGIN_CONTRACT §9), so the full report lives only
# in --out. This tool previously printed the report itself, which the runner classified as a
# malformed envelope -- error, never pass -- the moment gates started actually executing.
def _print_envelope(status: str, reasons: list[str], evidence: dict) -> None:
    print(
        json.dumps(
            {
                "kind": "img2.gate-verdict",
                "version": 1,
                "gate": "cs2-review",
                "plugin": "cs2",
                "status": status,
                "reasons": reasons,
                "evidence": evidence,
            },
            ensure_ascii=False,
        )
    )


class _EnvelopeParser(argparse.ArgumentParser):
    """argparse.error prints usage to stderr and exits 2 with EMPTY stdout, which the gate runner
    can only classify as an opaque malformed-envelope error. An unrecognized flag -- e.g. a newer
    gates.json against a stale installed tool -- must stay diagnosable, so the machine envelope is
    printed before exiting."""

    def error(self, message: str) -> None:  # type: ignore[override]
        _print_envelope("error", [message], {})
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = _EnvelopeParser(description="Evaluate the blocking CS2 review contract")
    parser.add_argument("--manifest", type=Path, help="validated cs2-intake.json (per-pass evaluation)")
    parser.add_argument("--metrics", type=Path, help="render/review metrics JSON (per-pass evaluation)")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--terminal-inputs", help="recompute terminal metrics from pinned workspace inputs")
    parser.add_argument("--prepare-scene", action="store_true",
                        help="produce per-pass scene policy from the current manifest; grants no terminal authority")
    parser.add_argument(
        "--scene",
        type=Path,
        default=Path("cs2-review-scene.json"),
        help="current workspace review scene; terminal mode checks exact reproducibility",
    )
    parser.add_argument("--out", type=Path, required=True, help="output review report JSON")
    # Strict is the DEFAULT: with no flag, deferral requests are refused and null metrics fail.
    # Only domain.json's per-pass row carries this flag; gates.json stays flagless, so a
    # copy-pasted or hand-edited terminal row fails closed, never open (design D1).
    parser.add_argument(
        "--allow-deferrals",
        action="store_true",
        help="honor the metrics file's deferred map for the closed deferrable gate set (per-pass invocations only)",
    )
    # No SystemExit wrapper: _EnvelopeParser.error() already printed the envelope and exits 2, and
    # catching here would also turn --help's normal exit 0 into a failure.
    args = parser.parse_args(argv)

    try:
        if args.prepare_scene:
            if args.manifest is None or args.metrics or args.terminal_inputs or args.allow_deferrals:
                raise ValueError("--prepare-scene requires only --manifest and --out")
            scene = _pass_scene(_load_object(args.manifest, "manifest"))
            _write_json_atomic(args.out, scene)
            print(json.dumps({"kind": "img2.cs2-pass-scene", "version": 1,
                              "scene": str(args.out), "terminalAuthority": False}))
            return 0
        if args.terminal_inputs:
            if args.allow_deferrals or args.manifest or args.metrics:
                raise ValueError("terminal inputs cannot be combined with deferrals or authored metrics")
            from cs2_terminal import _json, reproduce_terminal
            from cs2_evidence import read_workspace_file
            raw = read_workspace_file(args.workspace, args.terminal_inputs, role="terminal-inputs",
                                      missing_code="terminal-input-missing")
            result = reproduce_terminal(args.workspace, inputs=_json(raw, "terminal-inputs"))
            scene_path = args.scene if args.scene.is_absolute() else args.workspace / args.scene
            if load_review_scene(scene_path) != result["scene"]:
                raise ValueError("scene-not-reproducible")
            report = result["report"]
        else:
            if args.manifest is None or args.metrics is None:
                raise ValueError("--manifest and --metrics are required outside terminal replay")
            manifest = _load_object(args.manifest, "manifest")
            metrics = _load_object(args.metrics, "metrics")
            scene = load_review_scene(args.scene.expanduser())
            report = evaluate_knife_review(manifest, metrics, scene, allow_deferrals=args.allow_deferrals)
        _write_json_atomic(args.out, report)
        passed = report["verdict"] == "pass"
        # A deferred pass must be visible in the aggregate, not only in the report file: reasons
        # are machine-generated tokens, never the producer's free text (design D5).
        if passed:
            reasons = [f"deferred: {token}" for token in report["deferredGates"]]
        else:
            reasons = [str(item) for item in report.get("failedGates", [])] or ["review verdict: " + str(report["verdict"])]
        artifact_evidence = {"artifact": result["inputs"]["artifact"]} if args.terminal_inputs else {}
        _print_envelope(
            "pass" if passed else "fail",
            reasons,
            {
                **artifact_evidence,
                "report": str(args.out),
                "verdict": report["verdict"],
                "action": report.get("action"),
                "mode": report["mode"],
                "deferredGates": report["deferredGates"],
            },
        )
        return 0 if passed else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _print_envelope("error", [str(error)], {})
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
