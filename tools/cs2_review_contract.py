#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

GOLDEN_THRESHOLDS = {
    "silhouetteIoU": 0.85,
    "aspectRatioDelta": 0.05,
    "scaleDelta": 0.08,
    "paintedRegionMask": 0.85,
    "colorRegion": 0.80,
    "patternRegion": 0.75,
    "wearRegion": 0.70,
}


def build_review_scene(environment_hash: str) -> dict[str, Any]:
    return {
        "version": "cs2-knife-review-v1",
        "camera": {"fovDegrees": 40.0, "position": [0.0, 0.0, 3.0], "target": [0.0, 0.0, 0.0]},
        "objectTransform": {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
        "environmentHash": environment_hash,
        "exposure": 1.0,
        "toneMapping": "ACESFilmic",
        "resolution": [1024, 1024],
        "background": "#20242a",
        "rendererVersion": "three-r170",
        "thresholds": dict(GOLDEN_THRESHOLDS),
        "orbitViewpoints": [{"yaw": 35.0, "pitch": 8.0}, {"yaw": -35.0, "pitch": 8.0}],
    }


def validate_review_scene(scene: dict[str, Any]) -> list[str]:
    required = {"version", "camera", "objectTransform", "environmentHash", "exposure", "toneMapping", "resolution", "background", "rendererVersion", "thresholds", "orbitViewpoints"}
    errors = [f"missing {field}" for field in sorted(required - set(scene))]
    if scene.get("version") != "cs2-knife-review-v1":
        errors.append("unsupported review scene version")
    if scene.get("thresholds") != GOLDEN_THRESHOLDS:
        errors.append("golden thresholds do not match the frozen fixture contract")
    if len(scene.get("orbitViewpoints", [])) != 2:
        errors.append("exactly two orbit viewpoints are required")
    return errors

# Terminal review policy, formerly embedded only in the golden test scene.
# Keep the legacy projection contract above separate: it uses different metrics.
TERMINAL_THRESHOLDS = {
    "silhouetteIoU": 0.85,
    "aspectRatioDelta": 0.05,
    "scaleDelta": 0.08,
    "projectionCoverage": 0.85,
    "finishMaterialResponse": 0.8,
    "identityDetail": 0.8,
    "paintedRegion": 0.8,
    "maxOrbitCollapseRatio": 0.15,
}


def validate_terminal_thresholds(thresholds: Any) -> None:
    # Equality also rejects NaN/infinity; bool must not compare as an integer.
    if (not isinstance(thresholds, dict) or thresholds.keys() != TERMINAL_THRESHOLDS.keys()
            or any(type(thresholds[key]) not in (int, float) or thresholds[key] != expected
                   for key, expected in TERMINAL_THRESHOLDS.items())):
        raise ValueError("scene thresholds must exactly match the frozen terminal policy")
