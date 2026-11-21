#!/usr/bin/env python3
"""Evidence primitives shared by the CS2 metric producer and the terminal review gate.

Every refusal is an EvidenceError carrying a stable machine-readable reason code registered in
EXIT_CODES. Nothing here estimates, defaults or repairs: a file that is absent, unreadable, or whose
bytes do not match the digest recorded for it is refused under its own code.

Scope, stated plainly: this module checks integrity of the recorded bytes and their declared
bindings, not authenticity. A capture rendered from something other than the artifact it names,
or a hand-assembled classification and matching intake, cannot be detected here. The base host
owns any stronger provenance check.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from cs2_manifest import _classification_error

MAX_FILE_BYTES = 512 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
OUTPUT_KINDS = frozenset({"3d-object", "rigged-3d", "3d-scene"})

# Exit-code classes. A producer exits with the class of its refusal, so a caller can tell "something
# required is absent" from "something present is corrupt" from "evidence contradicts other evidence"
# from "the pixels cannot be measured" without parsing text. Exit 2 is reserved for usage errors.
EXIT_MISSING = 3
EXIT_INTEGRITY = 4
EXIT_BINDING = 5
EXIT_MEASUREMENT = 6

EXIT_CODES: dict[str, int] = {
    # something required is absent
    "artifact-missing": EXIT_MISSING,
    "intake-missing": EXIT_MISSING,
    "reference-undeclared": EXIT_MISSING,
    "reference-missing": EXIT_MISSING,
    "capture-missing": EXIT_MISSING,
    "classification-record-missing": EXIT_MISSING,
    "renderer-evidence-missing": EXIT_MISSING,
    # something present is unreadable or does not match its recorded digest
    "input-unreadable": EXIT_INTEGRITY,
    "input-digest-mismatch": EXIT_INTEGRITY,
    "artifact-invalid": EXIT_INTEGRITY,
    "artifact-file-mismatch": EXIT_INTEGRITY,
    "capture-record-invalid": EXIT_INTEGRITY,
    "image-undecodable": EXIT_INTEGRITY,
    "reference-digest-unrecorded": EXIT_INTEGRITY,
    "intake-invalid": EXIT_INTEGRITY,
    "classification-record-invalid": EXIT_INTEGRITY,
    # evidence contradicts other evidence, or is not what it claims to be
    "intake-not-ready": EXIT_BINDING,
    "capture-viewpoint-mismatch": EXIT_BINDING,
    "capture-artifact-mismatch": EXIT_BINDING,
    "capture-delivery-unlisted": EXIT_BINDING,
    "capture-delivery-mismatch": EXIT_BINDING,
    "capture-is-reference": EXIT_BINDING,
    "orbit-view-not-distinct": EXIT_BINDING,
    "classification-intake-missing": EXIT_BINDING,
    "classification-record-mismatch": EXIT_BINDING,
    "classification-identity-mismatch": EXIT_BINDING,
    "route-selection-invalid": EXIT_BINDING,
    "route-reference-mismatch": EXIT_BINDING,
    "route-object-mismatch": EXIT_BINDING,
    "metrics-not-produced": EXIT_BINDING,
    "artifact-binding-mismatch": EXIT_BINDING,
    "intake-binding-mismatch": EXIT_BINDING,
    "metrics-not-reproducible": EXIT_BINDING,
    "scene-not-reproducible": EXIT_BINDING,
    "scene-thresholds-not-frozen": EXIT_BINDING,
    # the pixels cannot be measured
    "subject-not-found": EXIT_MEASUREMENT,
    "capture-subject-not-found": EXIT_MEASUREMENT,
    "frame-aspect-mismatch": EXIT_MEASUREMENT,
    "terminal-input-missing": EXIT_MISSING,
    "terminal-input-invalid": EXIT_INTEGRITY,
    "terminal-binding-mismatch": EXIT_BINDING,
    "material-response-unmeasurable": EXIT_MEASUREMENT,
    "region-unmeasurable": EXIT_MEASUREMENT,
}


class EvidenceError(ValueError):
    """A refused piece of evidence. `reason_code` is the stable contract; `detail` is for humans."""

    def __init__(self, reason_code: str, detail: str, role: str | None = None) -> None:
        if reason_code not in EXIT_CODES:
            raise AssertionError(f"unregistered evidence reason code {reason_code!r}")
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail
        self.role = role

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.reason_code]

    @property
    def token(self) -> str:
        """The failedGates token the terminal review records for this refusal."""
        family = "classification" if self.reason_code.startswith(("classification-", "route-")) else "evidence"
        return f"{family}:{self.reason_code}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def serialize_json(payload: Any) -> bytes:
    """The one serialization every produced JSON file uses."""
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def canonical_digest(value: Any) -> str:
    return sha256_hex(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    )


def normalized(value: Any) -> Any:
    """A value as it reads back from its own serialization (tuples become lists, and so on)."""
    return strict_json(serialize_json(value))


def strict_json(data: bytes) -> Any:
    """Parse JSON rejecting duplicate keys and non-finite constants (both are smuggling routes)."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def constant(token: str) -> Any:
        raise ValueError(f"non-finite JSON constant {token}")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except UnicodeDecodeError as error:
        raise ValueError(f"not UTF-8: {error}") from error


def relative_parts(value: Any, role: str) -> tuple[str, ...]:
    if (not isinstance(value, str) or not value or "\\" in value or value.startswith("/")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise EvidenceError("input-unreadable", f"unsafe or empty path declared for {role}", role)
    parts = tuple(value.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise EvidenceError("input-unreadable", f"path declared for {role} is not a canonical relative path", role)
    return parts


def _slurp(fd: int, role: str) -> bytes:
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceError("input-unreadable", f"{role} is not a regular file", role)
        if info.st_size > MAX_FILE_BYTES:
            raise EvidenceError("input-unreadable", f"{role} exceeds the {MAX_FILE_BYTES} byte limit", role)
        data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise EvidenceError("input-unreadable", f"{role} exceeds the {MAX_FILE_BYTES} byte limit", role)
        return data


def read_workspace_file(root: Path, relative: Any, *, role: str, missing_code: str) -> bytes:
    """Read a regular file below `root` without following any symlink component.

    `missing_code` is the reason code for a file (or containing directory) that does not exist;
    every other failure to open it safely is `input-unreadable`."""
    parts = relative_parts(relative, role)
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise EvidenceError("input-unreadable", f"workspace is not readable ({error.strerror})", role) from error
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError as error:
        raise EvidenceError(missing_code, f"{relative} does not exist", role) from error
    except OSError as error:
        raise EvidenceError("input-unreadable", f"{relative} cannot be opened safely ({error.strerror})", role) from error
    finally:
        os.close(directory)
    return _slurp(fd, role)


def read_absolute_file(path: str, *, role: str, missing_code: str) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError as error:
        raise EvidenceError(missing_code, f"{path} does not exist", role) from error
    except OSError as error:
        raise EvidenceError("input-unreadable", f"{path} cannot be opened safely ({error.strerror})", role) from error
    return _slurp(fd, role)


def read_recorded_file(root: Path, recorded: Any, *, role: str, missing_code: str) -> bytes:
    """A path an earlier step recorded: absolute as the intake builder resolved it, or workspace-relative."""
    if isinstance(recorded, str) and os.path.isabs(recorded):
        return read_absolute_file(recorded, role=role, missing_code=missing_code)
    return read_workspace_file(root, recorded, role=role, missing_code=missing_code)


def check_digest(data: bytes, expected: str, role: str) -> None:
    actual = sha256_hex(data)
    if actual != expected:
        raise EvidenceError("input-digest-mismatch", f"{role} is {actual} but {expected} was recorded", role)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_artifact_identity(root: Path, relative: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Identity of the produced artifact -- manifest path and digest, objectId, outputKind -- and its file list.

    Every file the manifest lists is re-read and re-hashed, so a delivery that changed after
    artifact.json was written cannot ride on a still-matching manifest digest. Container validity of
    the delivery itself (is it a well-formed GLB) is the base's artifact validator's job, not this one's."""
    raw = read_workspace_file(root, relative, role="artifact", missing_code="artifact-missing")
    try:
        artifact = strict_json(raw)
    except ValueError as error:
        raise EvidenceError("artifact-invalid", f"{relative} is not strict JSON ({error})", "artifact") from error
    if not isinstance(artifact, dict):
        raise EvidenceError("artifact-invalid", f"{relative} must be a JSON object", "artifact")
    object_id = artifact.get("objectId")
    kind = artifact.get("outputKind")
    entries = artifact.get("files")
    if not isinstance(object_id, str) or not IDENTIFIER.fullmatch(object_id):
        raise EvidenceError("artifact-invalid", "objectId is missing or malformed", "artifact")
    if not isinstance(kind, str) or kind not in OUTPUT_KINDS:
        raise EvidenceError("artifact-invalid", "outputKind is missing or not a terminal 3D kind", "artifact")
    if not isinstance(entries, list) or not entries:
        raise EvidenceError("artifact-invalid", "files must be a non-empty list", "artifact")
    seen: set[str] = set()
    files: list[dict[str, str]] = []
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or not isinstance(entry.get("sha256"), str) or not SHA256.fullmatch(entry["sha256"])):
            raise EvidenceError("artifact-invalid", "every file entry needs a path and a sha256", "artifact")
        if entry["path"] in seen:
            raise EvidenceError("artifact-invalid", f"duplicate file entry {entry['path']}", "artifact")
        seen.add(entry["path"])
        role = f"artifact-file:{entry['path']}"
        try:
            data = read_workspace_file(root, entry["path"], role=role, missing_code="artifact-file-mismatch")
        except EvidenceError as error:
            if error.reason_code == "input-unreadable":
                raise EvidenceError("artifact-file-mismatch", error.detail, role) from error
            raise
        if sha256_hex(data) != entry["sha256"]:
            raise EvidenceError("artifact-file-mismatch", f"{entry['path']} no longer matches the digest artifact.json records", role)
        files.append({"path": entry["path"], "sha256": entry["sha256"]})
    identity = {"path": relative, "sha256": sha256_hex(raw), "objectId": object_id, "outputKind": kind}
    return identity, files


def reference_view(manifest: dict[str, Any]) -> dict[str, str]:
    views = manifest.get("sourceViews")
    matches = [view for view in views if isinstance(view, dict) and view.get("role") == "reference"] if isinstance(views, list) else []
    if len(matches) != 1:
        raise EvidenceError("reference-undeclared", "the intake must declare exactly one reference source view", "reference")
    path, digest = matches[0].get("path"), matches[0].get("sha256")
    if not isinstance(path, str) or not path:
        raise EvidenceError("reference-undeclared", "the intake's reference view records no path", "reference")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise EvidenceError("reference-digest-unrecorded", "the intake's reference view records no SHA-256", "reference")
    return {"path": path, "sha256": digest}


def verify_classification(
    root: Path,
    manifest: dict[str, Any],
    relative: str,
    artifact_object_id: str | None,
    reference_sha256: str | None,
) -> dict[str, Any]:
    """Check classification content and bindings, NOT provider authenticity.

    A recorded routeDecision may authorise entering the CS2 profile and nothing else: it carries no
    identity, so it can never satisfy this. The record must exist on disk independently of the
    intake, pass the same validator the manifest builder used, be identical to the copy the intake
    embeds and agree with the family/subtype the intake acted on; any route selection must name this
    reference and this artifact's object. `artifact_object_id` / `reference_sha256` are None only when
    the caller already refused the artifact / reference and is collecting further refusals."""
    raw = read_workspace_file(root, relative, role="classification", missing_code="classification-record-missing")
    try:
        record = strict_json(raw)
    except ValueError as error:
        raise EvidenceError("classification-record-invalid", f"{relative} is not strict JSON ({error})", "classification") from error
    problem = _classification_error(record)
    if problem is not None:
        raise EvidenceError("classification-record-invalid", problem, "classification")
    embedded = manifest.get("classification")
    if embedded is None:
        raise EvidenceError("classification-intake-missing", "the intake embeds no classification record", "classification")
    if embedded != record:
        raise EvidenceError("classification-record-mismatch", "the intake's embedded classification differs from the record on disk", "classification")
    if manifest.get("itemFamily") != record["itemFamily"] or manifest.get("subtype") != record.get("subtype"):
        raise EvidenceError("classification-identity-mismatch", "the intake's family/subtype contradict the classification record", "classification")
    extensions = manifest.get("extensions")
    route = extensions.get("routeSelection") if isinstance(extensions, dict) else None
    selection = None
    if route is not None:
        if not isinstance(route, dict) or route.get("profile") != "cs2":
            raise EvidenceError("route-selection-invalid", "the recorded route selection is not a CS2 profile selection", "route")
        if reference_sha256 is not None and route.get("referenceSha256") != reference_sha256:
            raise EvidenceError("route-reference-mismatch", "the route selected a different reference than the intake measures", "route")
        if artifact_object_id is not None and route.get("objectId") != artifact_object_id:
            raise EvidenceError("route-object-mismatch", "the route selected a different object than the artifact delivers", "route")
        selection = {key: route.get(key) for key in ("objectId", "decisionSha256", "referenceSha256", "resolvedSha")}
    return {
        "path": relative,
        "sha256": sha256_hex(raw),
        "canonicalSha256": canonical_digest(record),
        "itemFamily": record["itemFamily"],
        "subtype": record.get("subtype"),
        "confidence": record["confidence"],
        "provider": record["provider"],
        "version": record["version"],
        "routeSelection": selection,
    }
