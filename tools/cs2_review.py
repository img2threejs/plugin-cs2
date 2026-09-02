from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

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
REQUIRED_THRESHOLDS = {
    "silhouetteIoU",
    "aspectRatioDelta",
    "scaleDelta",
    "projectionCoverage",
    "finishMaterialResponse",
    "identityDetail",
    "paintedRegion",
    "maxOrbitCollapseRatio",
}

# The closed deferrable set: the gates whose metrics are produced by the projection bake and so
# cannot exist in passes before material-pass. Hardcoded HERE, never read from the scene fixture --
# --scene is a caller-supplied path, and a safety parameter must not live in swappable input
# (design D3). Keys are gate tokens, the same vocabulary failedGates uses. Geometry and orbit
# gates are never deferrable: renders exist in every pass, so a report can never be produced with
# zero evaluated gates.
DEFERRABLE_GATES = ("finishMaterialResponse", "identityDetail", "projection-coverage")
MAX_DEFERRAL_REASON_CHARS = 200
PLUGIN_VERSION = json.loads(
    (Path(__file__).resolve().parent.parent / "plugin.json").read_text(encoding="utf-8")
)["version"]


def load_review_scene(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("review scene must be a JSON object")
    missing = REQUIRED_SCENE_KEYS - payload.keys()
    if missing:
        raise ValueError("review scene is missing: " + ", ".join(sorted(missing)))
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict) or not REQUIRED_THRESHOLDS.issubset(thresholds):
        raise ValueError("review scene thresholds are incomplete")
    if payload.get("version") != 1:
        raise ValueError("unsupported review scene version")
    return payload


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _failed_threshold(metrics: dict[str, Any], key: str, threshold: float, *, maximum: bool) -> bool:
    value = metrics.get(key)
    if not _number(value):
        return True
    return float(value) > threshold if maximum else float(value) < threshold


def _metric_state(value: Any, threshold: float, *, maximum: bool = False) -> str:
    """"missing" | "failing" | "passing" -- the split _failed_threshold collapses. Deferral
    semantics need to tell a metric that does not exist yet from one that exists and fails: only
    the former is deferrable, and the latter under a declared deferral is a producer contradiction
    (deferral-conflict)."""
    if not _number(value):
        return "missing"
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


def _region_results(inputs: dict[str, Any], threshold: float) -> tuple[list[dict[str, Any]], list[str]]:
    raw = inputs.get("paintedRegions", [])
    if not isinstance(raw, list):
        return [], ["painted-regions-invalid"]
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


def _critical_feature_failures(inputs: dict[str, Any], default_threshold: float) -> list[str]:
    raw = inputs.get("criticalFeatures", [])
    if not isinstance(raw, list):
        return ["critical-features-invalid"]
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
    deferrals: dict[str, str] | None = None,
) -> dict[str, Any]:
    thresholds = review_scene["thresholds"]
    deferrals = deferrals if deferrals is not None else _load_deferrals(inputs)
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

    for key in ("silhouetteIoU", "aspectRatioDelta", "scaleDelta"):
        maximum = key != "silhouetteIoU"
        if _failed_threshold(inputs, key, float(thresholds[key]), maximum=maximum):
            failed.append(key)
    for key in ("finishMaterialResponse", "identityDetail"):
        state = _metric_state(inputs.get(key), float(thresholds[key]))
        if state == "missing":
            if honored(key):
                deferred_gates.append(key)
            else:
                failed.append(key)
        elif state == "failing":
            failed.append(key)
            if honored(key):
                failed.append(f"deferral-conflict:{key}")
        elif honored(key):
            spurious_deferrals.append(key)

    region_results, region_failures = _region_results(inputs, float(thresholds["paintedRegion"]))
    failed.extend(region_failures)
    failed.extend(_critical_feature_failures(inputs, float(thresholds["identityDetail"])))
    if not allow_deferrals:
        # Strict-door teeth for the vacuous arrays: empty iterates zero times and passed outright
        # at every door before this change. Non-emptiness, not set equality -- the scene's identity
        # lists are knife anatomy and this gate is family-neutral (design D7).
        for field, token in (("paintedRegions", "painted-regions-empty"), ("criticalFeatures", "critical-features-empty")):
            value = inputs.get(field)
            if value is None or (isinstance(value, list) and not value):
                failed.append(token)

    projection = inputs.get("projection")
    if manifest.get("route") == "reference-projection":
        if not isinstance(projection, dict) or projection.get("required") is not True:
            # Not deferrable, even under a declared projection-coverage deferral: deferring the
            # coverage number still requires declaring the projection obligation itself.
            failed.append("projection-evidence-missing")
        else:
            state = _metric_state(projection.get("coverage"), float(thresholds["projectionCoverage"]))
            if state == "missing":
                if honored("projection-coverage"):
                    deferred_gates.append("projection-coverage")
                else:
                    failed.append("projection-coverage")
            elif state == "failing":
                failed.append("projection-coverage")
                if honored("projection-coverage"):
                    failed.append("deferral-conflict:projection-coverage")
            elif honored("projection-coverage"):
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
            item.startswith(("manifest-state", "projection-evidence", "orbit-coverage", "deferral-"))
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
        "pluginVersion": PLUGIN_VERSION,
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
    parser.add_argument("--manifest", type=Path, required=True, help="validated cs2-intake.json")
    parser.add_argument("--metrics", type=Path, required=True, help="render/review metrics JSON")
    parser.add_argument(
        "--scene",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "knife_review_scene.json",
        help="versioned review scene fixture",
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
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    envelope = _print_envelope

    try:
        manifest = _load_object(args.manifest, "manifest")
        metrics = _load_object(args.metrics, "metrics")
        scene = load_review_scene(args.scene.expanduser())
        deferrals = _load_deferrals(metrics)
        report = evaluate_knife_review(
            manifest, metrics, scene,
            allow_deferrals=args.allow_deferrals, deferrals=deferrals,
        )
        _write_json_atomic(args.out, report)
        passed = report["verdict"] == "pass"
        # A deferred pass must be visible in the aggregate, not only in the report file: reasons
        # are machine-generated tokens, never the producer's free text (design D5).
        if passed:
            reasons = [f"deferred: {token}" for token in report["deferredGates"]]
        else:
            reasons = [str(item) for item in report.get("failedGates", [])] or ["review verdict: " + str(report["verdict"])]
        envelope(
            "pass" if passed else "fail",
            reasons,
            {
                "report": str(args.out),
                "verdict": report["verdict"],
                "action": report.get("action"),
                "mode": report["mode"],
                "deferredGates": report["deferredGates"],
            },
        )
        return 0 if passed else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        envelope("error", [str(error)], {})
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
