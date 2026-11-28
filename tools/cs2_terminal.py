#!/usr/bin/env python3
"""Deterministic CS2 terminal measurements and a narrow, program-owned host boundary.

Replay checks integrity, not authenticity. Only the host may authenticate classification,
source observations and journal quality review, or invoke the base delivered-GLB renderer.
No plugin-selected executable, provider name, digest or persisted receipt grants authority.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from cs2_evidence import (EvidenceError, SHA256, check_digest, normalized,
                          read_recorded_file, read_workspace_file, serialize_json,
                          sha256_hex, strict_json, write_bytes_atomic)
from cs2_measure import _sample, measure
from cs2_pixels import GRID, MIN_CORRELATION_CELLS, _correlation, _luma
from cs2_review_contract import TERMINAL_THRESHOLDS


def _ref(root, ref, role, bindings):
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref.get("sha256"), str) or not SHA256.fullmatch(ref["sha256"])):
        raise EvidenceError("terminal-input-invalid", f"{role} requires an exact path/sha256 binding", role)
    raw = read_workspace_file(root, ref["path"], role=role, missing_code="terminal-input-missing")
    check_digest(raw, ref["sha256"], role)
    binding = {"role": role, **ref}
    if binding not in bindings:
        bindings.append(binding)
    return raw


def _json(raw, role):
    try:
        value = strict_json(raw)
    except ValueError as exc:
        raise EvidenceError("terminal-input-invalid", f"{role}: {exc}", role) from exc
    if not isinstance(value, dict):
        raise EvidenceError("terminal-input-invalid", f"{role} must be an object", role)
    return value


def _required(value, key):
    if not isinstance(value, dict):
        raise EvidenceError("terminal-input-invalid", f"{key} requires an object")
    if key not in value:
        raise EvidenceError("terminal-input-missing", f"missing {key}", key)
    return value[key]


def _rois(source, key, reference):
    rows = _required(source, key)
    if not isinstance(rows, list) or not rows:
        raise EvidenceError("terminal-input-missing", f"nonempty annotated {key} required", key)
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "bounds"}:
            raise EvidenceError("terminal-input-invalid", f"invalid {key} annotation", key)
        ident, bounds = row["id"], row["bounds"]
        if (not isinstance(ident, str) or not ident or ident in seen or not isinstance(bounds, list)
                or len(bounds) != 4 or any(type(v) not in (float, int) or not math.isfinite(v) for v in bounds)
                or not 0 <= bounds[0] < bounds[2] <= 1 or not 0 <= bounds[1] < bounds[3] <= 1):
            raise EvidenceError("terminal-input-invalid", f"invalid {key} id/bounds", key)
        seen.add(ident)
        cells = [y * GRID + x for y in range(GRID) for x in range(GRID)
                 if bounds[0] <= (x + .5) / GRID < bounds[2]
                 and bounds[1] <= (y + .5) / GRID < bounds[3] and reference.subject[y * GRID + x]]
        if len(cells) < MIN_CORRELATION_CELLS:
            raise EvidenceError("region-unmeasurable", f"{key}:{ident} has too few source subject cells", key)
        result.append((ident, cells))
    return result


def _rms(values):
    return math.sqrt(math.fsum(v * v for v in values) / len(values))


def _score(value):
    return round(max(0., min(1., value)), 6)


def _capture(root, ref, config_ref, bindings, role):
    capture = _json(_ref(root, ref, role, bindings), role)
    config = _json(_ref(root, config_ref, role + "-config", bindings), role + "-config")
    recorded_config = _json(_ref(root, capture.get("config"), role + "-captured-config", bindings), "config")
    if recorded_config != config:
        raise EvidenceError("terminal-binding-mismatch", f"{role} config differs from pinned input", role)
    # Retain all exact renderer/config/pixel bytes for host quality authentication.
    for key in ("renderer", "screenshot"):
        recorded = capture.get(key)
        if not isinstance(recorded, dict):
            raise EvidenceError("terminal-input-invalid", f"{role} lacks {key}", role)
        _ref(root, {name: recorded.get(name) for name in ("path", "sha256")}, role + "-" + key, bindings)
    screenshot = capture["screenshot"]
    sample = _sample(read_workspace_file(root, screenshot["path"], role=role, missing_code="capture-missing"), "capture")
    return capture, config, sample


def reproduce_terminal(workspace, *, inputs):
    """Recompute all metrics from exact inputs; NEVER authenticate or authorize.

    Returns {inputs, manifest, metrics, scene, report, context}. Missing material
    observations/approved annotations refuse instead of substituting prose scores.
    """
    from cs2_review import evaluate_knife_review
    root = Path(workspace)
    inputs = normalized(inputs)
    if not isinstance(inputs, dict):
        raise EvidenceError("terminal-input-invalid", "terminal inputs must be an object")
    bindings = []
    objects = {}
    for role in ("intake", "classification", "artifact", "sources"):
        objects[role] = _json(_ref(root, _required(inputs, role), role, bindings), role)
    _ref(root, _required(inputs, "delivery"), "delivery", bindings)
    manifest, sources = objects["intake"], objects["sources"]
    reference_ref = _required(sources, "reference")
    reference_raw = _ref(root, reference_ref, "reference", bindings)
    reference = _sample(reference_raw, "reference")
    matches = [v for v in manifest.get("sourceViews", []) if isinstance(v, dict) and v.get("role") == "reference"]
    if len(matches) != 1 or matches[0].get("sha256") != reference_ref["sha256"]:
        raise EvidenceError("terminal-binding-mismatch", "approved source is not the intake reference")
    recorded = read_recorded_file(root, matches[0].get("path"), role="reference", missing_code="reference-missing")
    check_digest(recorded, reference_ref["sha256"], "reference")
    configs, captures = _required(inputs, "configs"), _required(inputs, "captures")
    if not isinstance(configs, list) or not isinstance(captures, list) or len(configs) != 3 or len(captures) != 3:
        raise EvidenceError("terminal-input-invalid", "three pinned configs and captures are required")
    for index, ref in enumerate(captures):
        _ref(root, ref, f"view-{index}", bindings)
    diagnostic = measure(root, intake_path=inputs["intake"]["path"], classification_path=inputs["classification"]["path"],
                         artifact_path=inputs["artifact"]["path"], capture_paths=[ref["path"] for ref in captures])
    rows = [_capture(root, cap, cfg, bindings, f"view-{index}") for index, (cap, cfg) in enumerate(zip(captures, configs))]
    if any(row[0].get("delivery") != inputs["delivery"] for row in rows):
        raise EvidenceError("terminal-binding-mismatch", "all views must capture the selected delivery")
    # D18 lists auxiliary files too; bind every byte to prevent hidden delivery changes.
    for index, file in enumerate(objects["artifact"].get("files", [])):
        _ref(root, {key: file.get(key) for key in ("path", "sha256")}, f"artifact-file-{index}", bindings)
    regions, features = _rois(sources, "regions", reference), _rois(sources, "criticalFeatures", reference)
    front = rows[0][2]
    region_results = []
    for ident, cells in regions:
        coverage = sum(front.subject[i] for i in cells) / len(cells)
        error = _rms([reference.rgb[i][c] - front.rgb[i][c] for i in cells for c in range(3)])
        region_results.append({"id": ident, "score": _score(min(coverage, 1 - error / 255)),
                               "confidence": _score(coverage), "referenceCells": len(cells)})
    feature_results = []
    for ident, cells in features:
        shared = [i for i in cells if front.subject[i]]
        correlation = _correlation([_luma(reference.rgb[i]) for i in shared], [_luma(front.rgb[i]) for i in shared])
        feature_results.append({"id": ident, "score": _score(min(len(shared) / len(cells), correlation))})
    material_views, material_captures = _required(sources, "materialViews"), _required(inputs, "materialCaptures")
    if (not isinstance(material_views, list) or len(material_views) < 2 or not isinstance(material_captures, list)
            or len(material_views) != len(material_captures)):
        raise EvidenceError("terminal-input-missing", "at least two matched material source/capture views required")
    material_samples, lighting = [], set()
    for index, (view, cap_ref) in enumerate(zip(material_views, material_captures)):
        if not isinstance(view, dict) or set(view) != {"source", "config"}:
            raise EvidenceError("terminal-input-invalid", "material view requires source and config bindings")
        source = _sample(_ref(root, view["source"], f"material-source-{index}", bindings), "reference")
        cap, config, sample = _capture(root, cap_ref, view["config"], bindings, f"material-{index}")
        # Reuse the production capture consistency validator, never a renderer-name shortcut.
        measure(root, intake_path=inputs["intake"]["path"], classification_path=inputs["classification"]["path"],
                artifact_path=inputs["artifact"]["path"], capture_paths=[cap_ref["path"], captures[1]["path"], captures[2]["path"]])
        if cap.get("delivery") != inputs["delivery"]:
            raise EvidenceError("terminal-binding-mismatch", "material capture names another delivery")
        if {k: v for k, v in config.items() if k not in {"lighting", "viewId"}} != {
                k: v for k, v in rows[0][1].items() if k not in {"lighting", "viewId"}}:
            raise EvidenceError("terminal-binding-mismatch", "material views may change lighting only")
        if (source.width, source.height) != (reference.width, reference.height):
            raise EvidenceError("frame-aspect-mismatch", "material source dimensions differ from reference")
        lighting.add(serialize_json(config.get("lighting")))
        material_samples.append((source, sample))
    if len(lighting) != len(material_views):
        raise EvidenceError("material-response-unmeasurable", "material lighting states must be distinct")
    response_scores = []
    for ident, cells in regions:
        for index in range(1, len(material_samples)):
            source_a, render_a = material_samples[0]
            source_b, render_b = material_samples[index]
            if any(not s.subject[i] for s in (source_a, source_b) for i in cells):
                raise EvidenceError("region-unmeasurable", f"material source does not cover region {ident}")
            source_delta = [source_b.rgb[i][c] - source_a.rgb[i][c] for i in cells for c in range(3)]
            magnitude = _rms(source_delta)
            if magnitude < 2:
                raise EvidenceError("material-response-unmeasurable", f"no measurable lighting response in region {ident}")
            delta_error = [render_b.rgb[i][c] - render_a.rgb[i][c] - delta
                           for delta, (i, c) in zip(source_delta, ((i, c) for i in cells for c in range(3)))]
            absolute_error = _rms([s.rgb[i][c] - r.rgb[i][c] for s, r in (material_samples[0], material_samples[index])
                                   for i in cells for c in range(3)])
            coverage = min(sum(r.subject[i] for i in cells) / len(cells) for r in (render_a, render_b))
            response_scores.append(_score(min(coverage, 1 - _rms(delta_error) / magnitude, 1 - absolute_error / 255)))
    front_area = sum(front.subject)
    collapse = [sum(row[2].subject) / front_area for row in rows[1:]]
    pass_id = _required(inputs, "passId")
    if not isinstance(pass_id, str) or not pass_id:
        raise EvidenceError("terminal-input-invalid", "passId must be nonempty")
    metrics = {"passId": pass_id, **{k: diagnostic["referenceView"][k] for k in (
        "silhouetteIoU", "aspectRatioDelta", "scaleDelta")},
        "finishMaterialResponse": min(response_scores),
        "identityDetail": min(row["score"] for row in feature_results),
        "paintedRegions": region_results, "criticalFeatures": feature_results,
        "projection": {"required": manifest.get("route") == "reference-projection",
                       "coverage": diagnostic["referenceView"]["coverage"]},
        "multiAngle": {"degenerate": any(ratio < TERMINAL_THRESHOLDS["maxOrbitCollapseRatio"] for ratio in collapse),
                       "angles": [{"id": row[0]["viewId"], "subjectAreaRatio": round(ratio, 6)}
                                  for row, ratio in zip(rows[1:], collapse)]},
        "measurementScope": "matched-lighting RGB response; annotated colour and structure agreement, not proven asset identity"}
    config = rows[0][1]
    scene = {"version": 1, "fixtureId": "workspace-delivered-glb-v1", "reference": reference_ref,
             "identity": {"family": manifest.get("itemFamily"), "criticalFeatures": [ident for ident, _ in features]},
             "camera": _required(config, "camera"), "transform": _required(config, "transform"),
             "environment": _required(config, "lighting"),
             "resolution": _required(config, "viewport"), "background": _required(config, "background"),
             "rendererVersion": rows[0][0]["renderer"],
             "calibration": {"status": "frozen-thresholds-not-an-independent-expert-corpus"},
             "thresholds": dict(TERMINAL_THRESHOLDS)}
    report = evaluate_knife_review(manifest, metrics, scene)
    context = {"kind": "img2.cs2-terminal-context", "version": 1, "artifact": inputs["artifact"],
               "objectId": objects["artifact"].get("objectId"), "passId": pass_id,
               "bindings": bindings, "metrics": metrics, "scene": scene,
               "requiredChecks": ["classification-source-authority", "finish-material-response", "identity-detail",
                                  *["region:" + row["id"] for row in region_results],
                                  *["feature:" + row["id"] for row in feature_results]],
               "authority": "none-replay-only"}
    for binding in bindings:
        _ref(root, {k: binding[k] for k in ("path", "sha256")}, binding["role"], [])
    return {"inputs": inputs, "manifest": manifest, "metrics": metrics, "scene": scene,
            "report": report, "context": context}


def produce_terminal(workspace, *, inputs, host, output_dir=".img2/cs2-terminal"):
    """Produce via the trusted base host, then demand authenticated semantic review.

    Host methods raise on refusal and return None except capture(), which returns
    a workspace {path,sha256}. The host implementation is supplied by trusted base
    code, never deserialized from plugin/workspace JSON. See README for signatures.
    """
    root, inputs = Path(workspace), normalized(inputs)
    from cs2_evidence import relative_parts
    relative_parts(output_dir, "terminal-output")
    if (root / output_dir).exists():
        raise EvidenceError("terminal-input-invalid", "output directory must be fresh")
    bindings = []
    for role in ("intake", "classification", "artifact", "sources", "delivery"):
        _ref(root, _required(inputs, role), role, bindings)
    sources = _json(_ref(root, inputs["sources"], "sources", bindings), "sources")
    reference = _sample(_ref(root, _required(sources, "reference"), "reference", bindings), "reference")
    _rois(sources, "regions", reference)
    _rois(sources, "criticalFeatures", reference)
    host.verify_classification(root, classification=inputs["classification"], reference=_required(sources, "reference"),
                               intake=inputs["intake"], artifact=inputs["artifact"])
    configs = _required(inputs, "configs")
    material = _required(sources, "materialViews")
    if not isinstance(configs, list) or len(configs) != 3 or not isinstance(material, list) or len(material) < 2:
        raise EvidenceError("terminal-input-missing", "three main and at least two material configs required")
    for index, view in enumerate(material):
        _sample(_ref(root, _required(view, "source"), f"material-source-{index}", bindings), "reference")
        _json(_ref(root, _required(view, "config"), f"material-config-{index}", bindings), "config")
    for index, config in enumerate(configs):
        _json(_ref(root, config, f"view-config-{index}", bindings), "config")
    host.verify_sources(root, sources=inputs["sources"], context={"inputs": inputs, "bindings": bindings})
    inputs["captures"], inputs["materialCaptures"] = [], []
    for target, entries, prefix in (("captures", configs, "view"),
                                     ("materialCaptures", [_required(view, "config") for view in material], "material")):
        for index, config_ref in enumerate(entries):
            config = _json(_ref(root, config_ref, f"{prefix}-config-{index}", bindings), "config")
            capture = host.capture(root, artifact=inputs["artifact"], delivery=inputs["delivery"], config=config,
                                   output_dir=f"{output_dir}/{prefix}-{index}")
            inputs[target].append(capture)
    result = reproduce_terminal(root, inputs=inputs)
    paths = {}
    for name in ("inputs", "metrics", "scene", "report", "context"):
        relative = f"{output_dir}/{name}.json"
        raw = serialize_json(result[name])
        write_bytes_atomic(root / relative, raw)
        paths[name] = {"path": relative, "sha256": sha256_hex(raw)}
    return _finalize_result(root, result, paths, host, output_dir)


def _finalize_result(root, result, paths, host, output_dir):
    inputs = result["inputs"]
    if result["report"]["verdict"] != "pass":
        return {"kind": "img2.cs2-terminal-handoff", "version": 1, "status": "rejected",
                "artifact": inputs["artifact"], "evidence": paths, "deliverable": False,
                "failedGates": result["report"]["failedGates"]}
    host.verify_quality(root, context=result["context"])
    fresh = reproduce_terminal(root, inputs=inputs)
    if fresh != result:
        raise EvidenceError("terminal-binding-mismatch", "terminal evidence changed during host review")
    for name, ref in paths.items():
        _ref(root, ref, "produced-" + name, [])
    handoff = {"kind": "img2.cs2-terminal-handoff", "version": 1, "status": "host-reviewed",
               "artifact": inputs["artifact"], "evidence": paths, "deliverable": False,
               "scope": "base-child-handoff-not-parent-terminal-authorization"}
    write_bytes_atomic(root / output_dir / "handoff.json", serialize_json(handoff))
    return handoff


def finalize_terminal(workspace, *, inputs, host, output_dir=".img2/cs2-terminal"):
    """Resume after the base authenticates review of already-produced context.

    Never recapture or trust persisted metrics. Reproduce every output byte and
    reauthenticate source/classification/quality against the exact current inputs.
    """
    from cs2_evidence import relative_parts
    relative_parts(output_dir, "terminal-output")
    root = Path(workspace)
    result = reproduce_terminal(root, inputs=inputs)
    paths = {}
    for name in ("inputs", "metrics", "scene", "report", "context"):
        ref = {"path": f"{output_dir}/{name}.json", "sha256": sha256_hex(serialize_json(result[name]))}
        _ref(root, ref, "produced-" + name, [])
        paths[name] = ref
    sources = _json(_ref(root, result["inputs"]["sources"], "sources", []), "sources")
    host.verify_classification(root, classification=result["inputs"]["classification"],
                               reference=sources["reference"], intake=result["inputs"]["intake"],
                               artifact=result["inputs"]["artifact"])
    host.verify_sources(root, sources=result["inputs"]["sources"], context={
        "inputs": result["inputs"], "bindings": result["context"]["bindings"]})
    return _finalize_result(root, result, paths, host, output_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay pinned CS2 terminal metrics; no authentication or authorization")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--inputs-sha256", required=True)
    args = parser.parse_args(argv)
    import json
    try:
        raw = _ref(args.workspace, {"path": args.inputs, "sha256": args.inputs_sha256}, "inputs", [])
        result = reproduce_terminal(args.workspace, inputs=_json(raw, "inputs"))
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["report"]["verdict"] == "pass" else 1
    except EvidenceError as exc:
        print(json.dumps({"status": "refused", "reasonCode": exc.reason_code, "detail": exc.detail, "deliverable": False}))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
