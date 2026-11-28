#!/usr/bin/env python3
"""Measure captured CS2 silhouettes; integrity checks are not producer authentication.

Consumes the delivered-GLB capture format and the existing CS2 intake. The output
is diagnostic evidence, not terminal approval or semantic/finish assessment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from cs2_evidence import (EvidenceError, check_digest, load_artifact_identity,
                          read_recorded_file, read_workspace_file, reference_view,
                          sha256_hex, strict_json, verify_classification)
from cs2_pixels import (ImageDecodeError, MAX_SUBJECT_FRACTION, MIN_SUBJECT_FRACTION,
                        decode_png, sample_image, silhouette_measures)


def _object(root, path, role, missing_code):
    raw = read_workspace_file(root, path, role=role, missing_code=missing_code)
    try:
        value = strict_json(raw)
    except ValueError as error:
        raise EvidenceError("input-unreadable", f"{role} is not strict JSON", role) from error
    if not isinstance(value, dict):
        raise EvidenceError("input-unreadable", f"{role} must be an object", role)
    return value, sha256_hex(raw)


def _recorded(root, ref, role, missing_code):
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str):
        raise EvidenceError("capture-record-invalid", f"{role} is not a digest-bound reference", role)
    data = read_workspace_file(root, ref["path"], role=role, missing_code=missing_code)
    check_digest(data, ref["sha256"], role)
    return data


def _sample(data, role):
    try:
        sampled = sample_image(decode_png(data))
    except ImageDecodeError as error:
        raise EvidenceError("image-undecodable", str(error), role) from error
    if not MIN_SUBJECT_FRACTION <= sampled.subject_fraction <= MAX_SUBJECT_FRACTION:
        raise EvidenceError("subject-not-found" if role == "reference" else "capture-subject-not-found",
                            "subject mask is outside the measurable fraction", role)
    return sampled


def measure(root, *, intake_path, classification_path, artifact_path, capture_paths):
    root = Path(root)
    if len(capture_paths) != 3 or len(set(capture_paths)) != 3:
        raise EvidenceError("orbit-view-not-distinct", "exactly three distinct capture records are required")
    intake, intake_sha = _object(root, intake_path, "intake", "intake-missing")
    if intake.get("state") != "proceed":
        raise EvidenceError("intake-not-ready", "intake state is not proceed", "intake")
    identity, files = load_artifact_identity(root, artifact_path)
    view = reference_view(intake)
    source = read_recorded_file(root, view["path"], role="reference", missing_code="reference-missing")
    check_digest(source, view["sha256"], "reference")
    classification = verify_classification(root, intake, classification_path, identity["objectId"], view["sha256"])
    reference = _sample(source, "reference")
    captures, samples, cameras, view_ids = [], [], set(), set()
    for path in capture_paths:
        capture, digest = _object(root, path, "capture", "capture-missing")
        if (capture.get("kind") != "img2.delivered-glb-capture" or capture.get("version") != 1
                or capture.get("status") != "captured" or not isinstance(capture.get("viewId"), str)
                or not capture["viewId"] or not isinstance(capture.get("camera"), dict)):
            raise EvidenceError("capture-record-invalid", "invalid delivered GLB capture", "capture")
        if capture.get("artifact") != {"path": identity["path"], "sha256": identity["sha256"]}:
            raise EvidenceError("capture-artifact-mismatch", "capture names another artifact", "capture")
        delivery = capture.get("delivery")
        if delivery not in files:
            raise EvidenceError("capture-delivery-unlisted", "capture delivery is not listed in artifact", "capture")
        _recorded(root, delivery, "delivery", "capture-delivery-mismatch")
        renderer_bytes = _recorded(root, capture.get("renderer"), "renderer", "renderer-evidence-missing")
        config_bytes = _recorded(root, capture.get("config"), "config", "capture-missing")
        try:
            renderer = strict_json(renderer_bytes)
            config = strict_json(config_bytes)
        except ValueError as error:
            raise EvidenceError("capture-record-invalid", "renderer or config is not strict JSON", "capture") from error
        if not isinstance(renderer, dict) or not isinstance(config, dict):
            raise EvidenceError("capture-record-invalid", "renderer or config is not an object", "capture")
        viewport, camera_config, runtime = config.get("viewport"), config.get("camera"), renderer.get("runtimeReport")
        if (not isinstance(viewport, dict) or not isinstance(camera_config, dict) or not isinstance(runtime, dict)
                or config.get("frame") != {"units": "m", "up": "+Y", "forward": "+Z"}
                or type(viewport.get("width")) is not int or viewport["width"] <= 0
                or type(viewport.get("height")) is not int or viewport["height"] <= 0):
            raise EvidenceError("capture-record-invalid", "capture config lacks frame, viewport or camera", "capture")
        expected_camera = dict(camera_config, aspect=viewport["width"] / viewport["height"])
        if (capture["viewId"] != config.get("viewId") or capture.get("frame") != config.get("frame")
                or capture.get("viewport") != viewport or capture["camera"] != expected_camera
                or runtime.get("camera") != expected_camera or runtime.get("viewport") != viewport
                or runtime.get("frame") != config.get("frame")
                or runtime.get("canvas") != {"width": viewport["width"], "height": viewport["height"]}
                or not isinstance(runtime.get("renderer"), dict)
                or runtime["renderer"].get("name") != "WebGLRenderer"
                or not isinstance(runtime.get("threeRevision"), str) or not runtime["threeRevision"]
                or runtime.get("deliverySha256") != delivery["sha256"]):
            raise EvidenceError("capture-viewpoint-mismatch", "capture, config and renderer disagree", "capture")
        screenshot = _recorded(root, capture.get("screenshot"), "screenshot", "capture-missing")
        sampled = _sample(screenshot, "capture")
        screenshot_ref = capture["screenshot"]
        if (screenshot_ref.get("width") != sampled.width or screenshot_ref.get("height") != sampled.height
                or screenshot_ref.get("byteLength") != len(screenshot)
                or viewport["width"] != sampled.width or viewport["height"] != sampled.height):
            raise EvidenceError("capture-viewpoint-mismatch", "capture dimensions disagree", "capture")
        if sampled.width * reference.height != reference.width * sampled.height:
            raise EvidenceError("frame-aspect-mismatch", "capture and reference aspect differ", "capture")
        camera = json.dumps(capture["camera"], sort_keys=True, separators=(",", ":"), allow_nan=False)
        if camera in cameras or capture["viewId"] in view_ids:
            raise EvidenceError("orbit-view-not-distinct", "capture views or cameras repeat", "capture")
        cameras.add(camera)
        view_ids.add(capture["viewId"])
        captures.append({"path": path, "sha256": digest, "viewId": capture["viewId"],
                         "screenshotSha256": sha256_hex(screenshot)})
        samples.append(sampled)
    return {"kind": "img2.cs2-capture-diagnostics", "version": 1,
            "status": "measured", "deliverable": False,
            "scope": "pixel-diagnostics-only-no-producer-authentication-or-terminal-approval",
            "intake": {"path": intake_path, "sha256": intake_sha}, "artifact": identity,
            "classification": classification, "reference": view, "captures": captures,
            "referenceView": silhouette_measures(reference, samples[0]),
            "subjectFractions": [sample.subject_fraction for sample in samples]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--intake", required=True)
    parser.add_argument("--classification", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--capture", action="append", required=True,
                        help="workspace-relative capture.json; pass reference view then two orbit views")
    args = parser.parse_args(argv)
    try:
        result = measure(args.workspace, intake_path=args.intake, classification_path=args.classification,
                         artifact_path=args.artifact, capture_paths=args.capture)
    except EvidenceError as error:
        print(json.dumps({"status": "refused", "reasonCode": error.reason_code,
                          "detail": error.detail, "deliverable": False}, sort_keys=True))
        return error.exit_code
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
