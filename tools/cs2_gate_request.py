"""Versioned, mechanical-only gate request replay. No host or routed authority."""
from __future__ import annotations

import os
from pathlib import Path
import re
import uuid

from cs2_evidence import (EvidenceError, SHA256, canonical_digest, check_digest, read_workspace_file,
                          serialize_json, sha256_hex, strict_json)
from cs2_terminal import reproduce_terminal

GLOBAL_REQUEST = ".img2/cs2-terminal/gate-request.json"
_RUN = re.compile(r"\.img2/cs2-terminal/run-[0-9a-f]{32}\Z")
_REQUEST = re.compile(r"\.img2/cs2-terminal/run-[0-9a-f]{32}/gate-request\.json\Z")


def _read(root, binding, role):
    raw = read_workspace_file(root, binding["path"], role=role, missing_code="terminal-input-missing")
    check_digest(raw, binding["sha256"], role)
    return raw


def _binding(value, filename):
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not isinstance(value["sha256"], str)
            or not SHA256.fullmatch(value["sha256"])):
        raise ValueError("terminal-request-binding-invalid")
    parent, _, name = value["path"].rpartition("/")
    if not _RUN.fullmatch(parent) or name != filename:
        raise ValueError("terminal-request-run-mismatch")
    return parent


def _publish_report(root, relative, raw):
    """Atomic no-clobber publication, anchored to a symlink-free existing run."""
    try:
        existing = read_workspace_file(root, relative, role="gate-report", missing_code="terminal-input-missing")
    except EvidenceError as error:
        if error.reason_code != "terminal-input-missing":
            raise
    else:
        if existing != raw:
            raise ValueError("terminal-request-report-conflict")
        return
    parts = relative.split("/")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".gate-review-" + uuid.uuid4().hex + ".tmp"
    created = False
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, parts[-1], src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            existing = read_workspace_file(root, relative, role="gate-report", missing_code="terminal-input-missing")
            if existing != raw:
                raise ValueError("terminal-request-report-conflict")
    finally:
        if created:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def replay_request(workspace, request_path):
    root = Path(workspace)
    if not isinstance(request_path, str) or (request_path != GLOBAL_REQUEST and not _REQUEST.fullmatch(request_path)):
        raise ValueError("terminal-request-path-invalid")
    selected_raw = read_workspace_file(root, request_path, role="gate-request", missing_code="terminal-input-missing")
    request = strict_json(selected_raw)
    if not isinstance(request, dict) or set(request) != {"kind", "version", "inputs", "scene"}:
        raise ValueError("terminal-request-schema-invalid")
    if request["kind"] != "img2.cs2-terminal-request":
        raise ValueError("terminal-request-kind-mismatch")
    if type(request["version"]) is not int or request["version"] != 1:
        raise ValueError("terminal-request-version-mismatch")
    run = _binding(request["inputs"], "inputs.json")
    if _binding(request["scene"], "scene.json") != run:
        raise ValueError("terminal-request-run-mismatch")
    run_request = run + "/gate-request.json"
    if request_path != GLOBAL_REQUEST and request_path != run_request:
        raise ValueError("terminal-request-run-mismatch")
    run_raw = read_workspace_file(root, run_request, role="run-request", missing_code="terminal-input-missing")
    if run_raw != selected_raw:
        raise ValueError("terminal-request-binding-mismatch")
    request_ref = {"path": run_request, "sha256": sha256_hex(run_raw)}
    inputs_raw = _read(root, request["inputs"], "terminal-inputs")
    scene_raw = _read(root, request["scene"], "terminal-scene")
    result = reproduce_terminal(root, inputs=strict_json(inputs_raw))
    if canonical_digest(strict_json(scene_raw)) != canonical_digest(result["scene"]):
        raise ValueError("scene-not-reproducible")
    report = result["report"]
    if report["mode"] != "strict" or report["deferredGates"]:
        raise ValueError("terminal-request-nonstrict-report")
    bound = [(request_ref, "run-request"), (request["inputs"], "terminal-inputs"),
             (request["scene"], "terminal-scene")]
    bound.extend((binding, binding["role"]) for binding in result["context"]["bindings"])

    def recheck():
        for binding, role in bound:
            _read(root, binding, role)
        current = read_workspace_file(root, request_path, role="gate-request", missing_code="terminal-input-missing")
        if current != selected_raw:
            raise ValueError("terminal-request-binding-mismatch")

    recheck()
    report_raw = serialize_json(report)
    report_ref = {"path": run + "/gate-review.json", "sha256": sha256_hex(report_raw)}
    _publish_report(root, report_ref["path"], report_raw)
    recheck()
    _read(root, report_ref, "gate-report")
    return report, {
        "artifact": result["inputs"]["artifact"], "request": request_ref,
        "inputs": request["inputs"], "scene": request["scene"], "report": report_ref,
        "scope": "mechanical-replay-only", "terminalAuthority": False,
        "verdict": report["verdict"], "action": report["action"],
        "mode": report["mode"], "deferredGates": report["deferredGates"],
    }
