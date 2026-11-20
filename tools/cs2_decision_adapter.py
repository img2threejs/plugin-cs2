"""Offline CS2 decision inputs. The base owns consultation, budget and application.

Bindings use the shared controller's {role, path, sha256} shape. Callers supply
expected digests from their current revision, not hashes invented by this adapter.
No snapshot, candidate or semantic answer can clear a blocking CS2 gate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from cs2_manifest import _classification_error, validate_manifest
from cs2_review import _write_json_atomic, evaluate_knife_review, load_review_scene
from cs2_spec_template import make_cs2_feature_targets

_GROUPS = {"routing", "build-strategy", "quality-review", "repair"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PLAN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_PLAN_KEYS = {"id", "passId", "components", "operations", "fieldPaths",
              "materialSources", "dependencies", "rigHandoff"}
_SCOPE_KEYS = {"pass_id", "pass_unlocked", "components", "operations", "field_paths",
               "authorized_sources", "available_dependencies", "rig_required", "rig_available"}
_PROTECTED = {"quality", "qualitycontract", "qualityfloor", "qualityfloors", "gate", "gates",
              "blocking", "blockinggates", "threshold", "thresholds", "policy", "policyversion",
              "criticalfeatures", "acceptance", "decisionrefs", "permissions", "provenance"}
_MATERIAL_FIELDS = {"material", "materials", "materialParams", "referencePbr", "textureProjection",
                    "color", "roughness", "metalness", "normalMap", "map"}
_GEOMETRY_FIELDS = {"geometry", "primitive", "dimensions", "position", "rotation", "scale", "topology"}
_FORBIDDEN_OPERATIONS = {"disable-gate", "lower-threshold", "hide-component",
                         "remove-required-component", "unlock-pass", "change-policy"}


def _read_binding(workspace: Path, binding: dict[str, Any]) -> bytes:
    if not isinstance(binding, dict) or set(binding) != {"role", "path", "sha256"}:
        raise ValueError("invalid evidence binding")
    role, relative, expected = binding["role"], binding["path"], binding["sha256"]
    if not isinstance(role, str) or not _ID.fullmatch(role):
        raise ValueError("invalid evidence role")
    if not isinstance(expected, str) or not _SHA.fullmatch(expected):
        raise ValueError("invalid evidence SHA256")
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or Path(relative).is_absolute() or any(p in {"", ".", ".."} for p in relative.split("/"))):
        raise ValueError("unsafe evidence path")
    directory = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative.split("/")
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("evidence must be a regular file")
            data = handle.read()
    finally:
        os.close(directory)
    if not data or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"missing or stale evidence: {role}")
    return data


def _object(data: bytes, role: str) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"{role} must be a JSON object")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _protected(path: str) -> bool:
    return any(part.lower().replace("_", "").replace("-", "") in _PROTECTED for part in path.split("."))


def _protected_values(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = prefix + "." + key if prefix else key
            if _protected(key):
                result[path] = item
            else:
                result.update(_protected_values(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.update(_protected_values(item, prefix + "." + str(index)))
    return result


def _changes(before: Any, after: Any, prefix: str = "") -> set[str]:
    if _canonical(before) == _canonical(after):
        return set()
    if isinstance(before, dict) and isinstance(after, dict):
        fields: set[str] = set()
        for key in before.keys() | after.keys():
            if "." in key:
                raise ValueError("ambiguous component field path")
            path = prefix + "." + key if prefix else key
            if key not in before or key not in after:
                fields.add(path)
            else:
                fields.update(_changes(before[key], after[key], path))
        return fields
    return {prefix}


def _concrete_plans(
    spec: dict[str, Any], data: dict[str, bytes], bindings: list[dict[str, Any]],
    plan_input: dict[str, Any] | None, pass_id: str, unlocked: bool, *, repair: bool = False,
) -> list[dict[str, Any]]:
    """Project only concrete proposals admitted by an independent trusted base scope.

    This local prefilter does not replace StrategyDecision/filter_plans or the
    base's spec/provenance validator. No scope is derived from a model proposal,
    filename, manifest, candidate or hash. Missing trusted scope yields no plan.
    """
    if plan_input is None:
        return []
    if (not isinstance(plan_input, dict) or set(plan_input) != {"plans", "scope", "proposalRoles"}
            or not isinstance(plan_input["plans"], list) or not isinstance(plan_input["proposalRoles"], dict)):
        raise ValueError("invalid trusted plan input")
    scope = plan_input["scope"]
    expected_scope = _SCOPE_KEYS | ({"permissions"} if repair else set())
    if not isinstance(scope, dict) or set(scope) != expected_scope:
        raise ValueError("invalid trusted plan scope")
    for key in ("pass_unlocked", "rig_required", "rig_available"):
        if type(scope[key]) is not bool:
            raise ValueError("invalid trusted plan scope")
    for key in ("components", "operations", "field_paths", "authorized_sources", "available_dependencies",
                *(("permissions",) if repair else ())):
        values = scope[key]
        if (type(values) not in (list, set, frozenset) or any(not isinstance(v, str) or not v for v in values)
                or len(values) != len(set(values))):
            raise ValueError("invalid trusted plan allowlist")
    if any(not _SHA.fullmatch(value) for value in scope["authorized_sources"]):
        raise ValueError("invalid authorized material SHA256")
    if not unlocked or scope["pass_unlocked"] is not True or scope["pass_id"] != pass_id:
        return []
    if repair and "write-spec" not in scope["permissions"]:
        return []
    tree = spec.get("componentTree")
    if not isinstance(tree, list) or not tree:
        return []
    before = {item["id"]: item for item in tree}
    if len(before) != len(tree):
        raise ValueError("duplicate source component id")
    bound_hashes = {item["sha256"] for item in bindings}
    eligible: list[dict[str, Any]] = []
    seen: set[str] = set()
    for plan in plan_input["plans"]:
        if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS:
            raise ValueError("invalid shared plan shape")
        ident = plan["id"]
        if not isinstance(ident, str) or not _PLAN_ID.fullmatch(ident) or ident in seen:
            raise ValueError("invalid or duplicate plan id")
        seen.add(ident)
        if plan["passId"] != pass_id or type(plan["rigHandoff"]) is not bool:
            continue
        valid = True
        for name, allowed in (("components", set(scope["components"]) & before.keys()),
                              ("operations", set(scope["operations"])),
                              ("fieldPaths", set(scope["field_paths"])),
                              ("dependencies", set(scope["available_dependencies"])),
                              ("materialSources", set(scope["authorized_sources"]) & bound_hashes)):
            values = plan[name]
            if (not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values)
                    or len(values) != len(set(values)) or not set(values) <= allowed):
                valid = False
                break
        if (not valid or not plan["components"] or not plan["operations"] or not plan["fieldPaths"]
                or any(not _FIELD.fullmatch(field) or _protected(field) for field in plan["fieldPaths"])
                or any(not _SHA.fullmatch(value) for value in plan["materialSources"])
                or set(plan["operations"]) & _FORBIDDEN_OPERATIONS
                or (scope["rig_required"] and (not plan["rigHandoff"] or not scope["rig_available"]))):
            continue
        if (any(set(field.split(".")) & _MATERIAL_FIELDS for field in plan["fieldPaths"])
                and not plan["materialSources"]):
            continue
        role = plan_input["proposalRoles"].get(ident)
        if not isinstance(role, str) or role not in data:
            continue
        proposal = _object(data[role], role)
        proposed_tree = proposal.get("componentTree")
        if (not isinstance(proposed_tree, list)
                or any(not isinstance(item, dict) for item in proposed_tree)
                or [item.get("id") for item in proposed_tree] != [item["id"] for item in tree]
                or _canonical({key: value for key, value in spec.items() if key != "componentTree"})
                != _canonical({key: value for key, value in proposal.items() if key != "componentTree"})
                or _canonical(_protected_values(spec)) != _canonical(_protected_values(proposal))):
            continue
        changed = False
        for old, new in zip(tree, proposed_tree):
            fields = _changes(old, new)
            if fields and (old["id"] not in plan["components"]
                           or any(field not in plan["fieldPaths"] or _protected(field) for field in fields)):
                valid = False
                break
            changed = changed or bool(fields)
        if valid and changed:
            eligible.append(copy.deepcopy(plan))
    return eligible


def build_snapshot(
    workspace: Path, group: str, bindings: list[dict[str, Any]], *, pass_id: str,
    unlocked: bool = False, plan_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return fresh local inputs for the base controller, not a decision record.

    This is a local evidence manifest, not provider projection: paths remain only
    in bindings. The base strips them and independently rechecks every binding.
    """
    if group not in _GROUPS or not isinstance(pass_id, str) or not _ID.fullmatch(pass_id):
        raise ValueError("invalid decision group or pass id")
    if group in {"build-strategy", "repair"} and not _PLAN_ID.fullmatch(pass_id):
        raise ValueError("invalid shared plan pass id")
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("evidence bindings are required")
    workspace = workspace.expanduser().absolute()
    data: dict[str, bytes] = {}
    for binding in bindings:
        raw = _read_binding(workspace, binding)
        if binding["role"] in data:
            raise ValueError("duplicate evidence role")
        data[binding["role"]] = raw
    roles = set(data)
    required = {"manifest", "reference"}
    if group in {"quality-review", "repair"}:
        required |= {"spec", "source", "metrics", "review-scene", "gate", "camera", "render",
                     "view-front", "view-orbit-a", "view-orbit-b"}
    if group == "build-strategy" and plan_input is not None:
        required |= {"spec", "source", "critical-features"}
    if not required <= roles:
        raise ValueError("missing evidence roles: " + ", ".join(sorted(required - roles)))
    manifest = _object(data["manifest"], "manifest")
    if (not validate_manifest(manifest) or manifest.get("state") != "proceed"
            or manifest.get("admission", {}).get("admitted") is not True):
        raise ValueError("manifest or admission blocks the decision")
    error = _classification_error(manifest.get("classification"))
    if error:
        raise ValueError(error)
    reference_sha = hashlib.sha256(data["reference"]).hexdigest()
    if not any(isinstance(view, dict) and view.get("role") == "reference" and view.get("sha256") == reference_sha
               for view in manifest["sourceViews"]):
        raise ValueError("reference does not match the manifest's SHA256 evidence")
    spec = _object(data["spec"], "spec") if "spec" in data else {}
    targets = spec.get("featureTargets", make_cs2_feature_targets("componentAdapter" in manifest))
    tree = spec.get("componentTree", [])
    if not isinstance(tree, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
                                         or not _ID.fullmatch(item["id"]) for item in tree):
        raise ValueError("invalid component scope")
    if not isinstance(targets, list):
        raise ValueError("feature targets must be a list")
    features = []
    for feature in targets:
        if not isinstance(feature, dict) or not isinstance(feature.get("id"), str) or not _ID.fullmatch(feature["id"]):
            raise ValueError("invalid critical feature")
        if feature.get("mustPass") or feature.get("tier") == "critical":
            features.append({"id": feature["id"], "threshold": 3})
    candidates: list[dict[str, Any]] = []
    observations: dict[str, Any] = {"classificationConfidence": manifest["classification"]["confidence"],
                                    "availableViews": [], "images": []}
    gate = None
    if group in {"quality-review", "repair"}:
        metrics = _object(data["metrics"], "metrics")
        scene = _object(data["review-scene"], "review-scene")
        canonical_scene = load_review_scene(Path(__file__).resolve().parents[1] / "tests/fixtures/knife_review_scene.json")
        if scene.get("thresholds") != canonical_scene["thresholds"]:
            raise ValueError("decision snapshots cannot change frozen CS2 gate thresholds")
        if metrics.get("passId") != pass_id:
            raise ValueError("metrics belong to another pass")
        gate = evaluate_knife_review(manifest, metrics, scene)
        if gate != _object(data["gate"], "gate"):
            raise ValueError("gate report is stale or does not match current strict evaluation")
        observations.update({"failedGates": gate["failedGates"],
                             "availableViews": ["front", "orbit-a", "orbit-b"],
                             "images": [{"role": "reference", "asset": "reference"},
                                        {"role": "render", "asset": "render"}]})
        if group == "repair":
            if not gate["failedGates"]:
                raise ValueError("repair requires a fresh failed gate")
            plans = _concrete_plans(spec, data, bindings, plan_input, pass_id, unlocked, repair=True)
            for plan in plans:
                roots = {field.split(".")[0] for field in plan["fieldPaths"]}
                if roots <= _MATERIAL_FIELDS:
                    hypothesis, prefixes = "material", ("finishMaterialResponse", "identityDetail", "painted-region:")
                elif roots <= _GEOMETRY_FIELDS:
                    hypothesis, prefixes = "geometry", ("silhouetteIoU", "aspectRatioDelta", "scaleDelta", "critical-feature:")
                else:
                    continue
                if any(token.startswith(prefixes) for token in gate["failedGates"]):
                    candidates.append({"id": plan["id"], "hypothesis": hypothesis, "action": "refine-spec",
                                       "plan": plan, "permissions": ["write-spec"]})
    elif group == "build-strategy":
        candidates = _concrete_plans(spec, data, bindings, plan_input, pass_id, unlocked)
    # Recheck after evaluation so a mid-snapshot edit cannot combine revisions.
    for binding in bindings:
        _read_binding(workspace, binding)
    return {"kind": "img2.cs2-decision-snapshot", "version": 1, "group": group,
            "passId": pass_id, "bindings": copy.deepcopy(bindings), "candidates": candidates,
            "observations": observations,
            "requirements": {"criticalFeatures": features,
                             "requiredViews": ["front", "orbit-a", "orbit-b"],
                             "evidenceRoles": sorted(required)},
            "gate": gate, "authority": "advisory-input-only"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--group", choices=sorted(_GROUPS), required=True)
    parser.add_argument("--evidence", type=Path, required=True, help="JSON list of current revision bindings")
    parser.add_argument("--pass-id", required=True)
    parser.add_argument("--unlocked", action="store_true", help="base confirms this pass is unlocked")
    parser.add_argument("--plan-input", type=Path, help="trusted base scope, exact plans and bound successor proposal roles; not authorization")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = args.evidence if args.evidence.is_absolute() else args.workspace / args.evidence
        plan_path = args.plan_input
        if plan_path is not None and not plan_path.is_absolute():
            plan_path = args.workspace / plan_path
        plan_input = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path is not None else None
        result = build_snapshot(args.workspace, args.group, json.loads(evidence.read_text(encoding="utf-8")),
                                pass_id=args.pass_id, unlocked=args.unlocked, plan_input=plan_input)
        output = args.out if args.out.is_absolute() else args.workspace / args.out
        _write_json_atomic(output, result)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
