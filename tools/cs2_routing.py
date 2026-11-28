"""CS2 profile intent handoff, not classification or base routing authority.

The base caller must validate its journal, lease, eligibility and current inputs first,
then supply the canonical digest it validated independently of the route document.
This plugin checks that handoff's content/pin/object/reference bindings. A digest is
not an authentication token: untrusted callers cannot establish base authority here.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SHA = re.compile(r"[0-9a-f]{64}\Z")


def decision_digest(decision: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        decision, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def validate_route_selection(
    decision: dict[str, Any], *, validated_decision_sha256: str,
    object_id: str, resolved_sha: str, reference_sha256: str,
) -> dict[str, Any]:
    """Consume only a base-validated D8 selection; never return identity fields."""
    for value in (validated_decision_sha256, reference_sha256):
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            raise ValueError("independent validated route and reference SHA256 are required")
    if not isinstance(resolved_sha, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", resolved_sha):
        raise ValueError("resolved provider SHA is required")
    if not isinstance(object_id, str) or not object_id:
        raise ValueError("routed object id is required")
    if not isinstance(decision, dict) or decision_digest(decision) != validated_decision_sha256:
        raise ValueError("route decision differs from the independently validated digest")
    if (decision.get("kind") != "img2.route-decision" or type(decision.get("version")) is not int
            or decision["version"] != 1 or decision.get("phase") != "decided"
            or decision.get("suspendedAt") is not None):
        raise ValueError("route decision must be a completed img2.route-decision v1")
    if decision.get("imageSha256") != reference_sha256:
        raise ValueError("route reference is stale or belongs to another image")
    objects = decision.get("objects")
    if not isinstance(objects, list) or not all(isinstance(item, dict) for item in objects):
        raise ValueError("route objects are invalid")
    ids = [item.get("objectId") for item in objects]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("route object ids must be unique")
    matches = [item for item in objects if item["objectId"] == object_id]
    if len(matches) != 1:
        raise ValueError("route does not bind the requested object")
    item = matches[0]
    candidate = f"profile:cs2@{resolved_sha}"
    if (item.get("status") not in {"resolved", "best-of-n"}
            or not isinstance(item.get("eligible"), list)
            or not isinstance(item.get("selected"), list)
            or candidate not in item["eligible"] or candidate not in item["selected"]
            or any(value not in item["eligible"] for value in item["selected"])):
        raise ValueError("route has no eligible, selected CS2 profile at the resolved pin")
    return {"profile": "cs2", "candidateId": candidate, "objectId": object_id,
            "decisionSha256": validated_decision_sha256, "referenceSha256": reference_sha256,
            "resolvedSha": resolved_sha, "authority": "base-validated-profile-selection-only"}
