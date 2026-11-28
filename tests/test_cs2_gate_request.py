"""Fictional lantern protocol evidence, never native/host approval or terminal authority."""
from __future__ import annotations

import os
import subprocess
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from cs2_evidence import EvidenceError, serialize_json, sha256_hex
from cs2_manifest import build_classification_record
from cs2_terminal import reproduce_terminal


def lantern_png(shade):
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))
    rows = []
    for y in range(40):
        row = bytearray()
        for x in range(40):
            # An abstract glowing panel, not a traced real object or game asset.
            value = shade if 10 <= x < 30 and 8 <= y < 32 else 240
            row.extend((value, value, value))
        rows.append(b"\0" + row)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 40, 40, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def lantern_glb():
    # A self-contained, nonfunctional colored cube: no mechanism or external URI.
    vertices = [(-.25, -.25, -.25), (.25, -.25, -.25), (.25, .25, -.25), (-.25, .25, -.25),
                (-.25, -.25, .25), (.25, -.25, .25), (.25, .25, .25), (-.25, .25, .25)]
    indices = [0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4,
               3, 7, 6, 3, 6, 2, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5]
    binary = b"".join(struct.pack("<3f", *point) for point in vertices) + struct.pack("<36H", *indices)
    document = {
        "asset": {"version": "2.0", "generator": "fictional-lantern-protocol-fixture"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [.2, .8, .4, 1],
                                                "metallicFactor": 0, "roughnessFactor": 1},
                       "emissiveFactor": [.1, .3, .1]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 96, "target": 34962},
                        {"buffer": 0, "byteOffset": 96, "byteLength": 72, "target": 34963}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
                       "min": [-.25] * 3, "max": [.25] * 3},
                      {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"}],
    }
    raw = json.dumps(document, separators=(",", ":")).encode()
    raw += b" " * (-len(raw) % 4)
    return (struct.pack("<III", 0x46546c67, 2, 12 + 8 + len(raw) + 8 + len(binary))
            + struct.pack("<I4s", len(raw), b"JSON") + raw
            + struct.pack("<I4s", len(binary), b"BIN\0") + binary)


class LanternWorkspace:
    """Fabricated capture records test integrity only, not that the cube was rendered."""

    def __init__(self, root):
        self.root = Path(root)
        reference = self.put("lantern/reference.png", lantern_png(32))
        classification = build_classification_record("prop", "fictional-lantern", .99,
                                                     ["owned-synthetic-protocol-only"],
                                                     provider="synthetic-no-host-authority")
        classifier = self.put("lantern/classification.json", classification)
        intake = self.put("lantern/intake.json", {
            "state": "proceed", "itemFamily": "prop", "subtype": "fictional-lantern",
            "route": "reference-projection", "classification": classification,
            "sourceViews": [{"role": "reference", **reference}],
        })
        self.delivery = self.put("lantern/model.glb", lantern_glb())
        artifact = self.put("lantern/artifact.json", {
            "objectId": "fictional-lantern", "outputKind": "3d-object", "files": [self.delivery],
        })
        configs, captures = [], []
        for index in range(3):
            config = {"viewId": f"lantern-view-{index}",
                      "camera": {"position": [index, 0, 3]},
                      "viewport": {"width": 40, "height": 40, "devicePixelRatio": 1},
                      "frame": {"units": "m", "up": "+Y", "forward": "+Z"},
                      "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
                      "lighting": {"ambient": {"color": 16777215, "intensity": 1}}, "background": 15790320}
            config_ref, capture = self.capture(f"main-{index}", config, artifact, 32)
            configs.append(config_ref)
            captures.append(capture)
        material_views, material_captures = [], []
        base_config = json.loads((self.root / configs[0]["path"]).read_text())
        for index, shade in enumerate((32, 80)):
            config = dict(base_config, viewId=f"lantern-material-{index}",
                          lighting={"ambient": {"color": 16777215, "intensity": index + 1}})
            source = self.put(f"lantern/material-source-{index}.png", lantern_png(shade))
            config_ref, capture = self.capture(f"material-{index}", config, artifact, shade)
            material_views.append({"source": source, "config": config_ref})
            material_captures.append(capture)
        sources = self.put("lantern/sources.json", {
            "reference": reference, "regions": [{"id": "glowing-panel", "bounds": [.3, .3, .7, .7]}],
            "criticalFeatures": [{"id": "printed-star", "bounds": [.3, .3, .7, .7]}],
            "materialViews": material_views,
        })
        self.inputs = {"intake": intake, "classification": classifier, "artifact": artifact,
                       "delivery": self.delivery, "sources": sources, "configs": configs,
                       "captures": captures, "materialCaptures": material_captures,
                       "passId": "fictional-lantern-pass"}

    def put(self, path, value):
        raw = value if isinstance(value, bytes) else serialize_json(value)
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {"path": path, "sha256": sha256_hex(raw)}

    def capture(self, name, config, artifact, shade):
        config_ref = self.put(f"lantern/{name}-config.json", config)
        camera = dict(config["camera"], aspect=1.0)
        renderer = self.put(f"lantern/{name}-renderer.json", {"runtimeReport": {
            "camera": camera, "viewport": config["viewport"], "frame": config["frame"],
            "canvas": {"width": 40, "height": 40}, "renderer": {"name": "WebGLRenderer"},
            "threeRevision": "synthetic-not-rendered", "deliverySha256": self.delivery["sha256"],
        }})
        raw = lantern_png(shade)
        screenshot = dict(self.put(f"lantern/{name}.png", raw), width=40, height=40, byteLength=len(raw))
        capture = self.put(f"lantern/{name}-capture.json", {
            "kind": "img2.delivered-glb-capture", "version": 1, "status": "captured",
            "artifact": artifact, "delivery": self.delivery, "viewId": config["viewId"],
            "camera": camera, "frame": config["frame"], "viewport": config["viewport"],
            "renderer": renderer, "config": config_ref, "screenshot": screenshot,
        })
        return config_ref, capture


class LanternReplayTests(unittest.TestCase):
    def test_fictional_lantern_replay_is_non_authorizing_and_changed_delivery_refuses(self):
        with tempfile.TemporaryDirectory(prefix="cs2-lantern-protocol-") as temporary:
            fixture = LanternWorkspace(temporary)
            replay = reproduce_terminal(fixture.root, inputs=fixture.inputs)
            self.assertEqual(replay["report"]["verdict"], "pass")
            self.assertEqual(replay["context"]["authority"], "none-replay-only")
            self.assertFalse((fixture.root / ".img2/cs2-terminal/handoff.json").exists())
            (fixture.root / fixture.delivery["path"]).write_bytes(b"changed-fictional-cube")
            with self.assertRaisesRegex(EvidenceError, "input-digest-mismatch"):
                reproduce_terminal(fixture.root, inputs=fixture.inputs)


class GateRequestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cs2-lantern-request-")
        self.addCleanup(temporary.cleanup)
        self.fixture = LanternWorkspace(temporary.name)
        self.root = self.fixture.root
        home = self.root / "home"
        home.mkdir()
        self.env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
        self.replay = reproduce_terminal(self.root, inputs=self.fixture.inputs)
        self.run = ".img2/cs2-terminal/run-" + "a" * 32
        self.path, self.request = self.request_for(self.run)

    def request_for(self, run):
        inputs = self.fixture.put(run + "/inputs.json", self.fixture.inputs)
        scene = self.fixture.put(run + "/scene.json", self.replay["scene"])
        request = {"kind": "img2.cs2-terminal-request", "version": 1, "inputs": inputs, "scene": scene}
        path = run + "/gate-request.json"
        self.fixture.put(path, request)
        return path, request

    def invoke(self, path=None, *extra):
        return subprocess.run([sys.executable, str(ROOT / "tools/cs2_review.py"),
                               "--workspace", str(self.root), "--terminal-request", path or self.path, *extra],
                              cwd=self.root, env=self.env, capture_output=True, text=True, timeout=30)

    def refuse(self, path=None, *extra):
        result = self.invoke(path, *extra)
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "error")
        return result

    def test_explicit_request_binds_deterministic_report_and_no_authority(self):
        sentinel = self.fixture.put("cs2-review.json", {"unrelated": "preserve"})
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        envelope = json.loads(result.stdout)
        evidence = envelope["evidence"]
        self.assertEqual(envelope["status"], "pass")
        self.assertEqual(evidence["request"], {"path": self.path, "sha256": sha256_hex((self.root / self.path).read_bytes())})
        for role in ("inputs", "scene"):
            self.assertEqual(evidence[role], self.request[role])
        self.assertEqual(evidence["artifact"], self.fixture.inputs["artifact"])
        self.assertEqual(evidence["scope"], "mechanical-replay-only")
        self.assertIs(evidence["terminalAuthority"], False)
        self.assertEqual((evidence["verdict"], evidence["action"], evidence["mode"], evidence["deferredGates"]),
                         ("pass", "continue", "strict", []))
        report = self.root / self.run / "gate-review.json"
        self.assertEqual(report.read_bytes(), serialize_json(self.replay["report"]))
        self.assertEqual(evidence["report"], {"path": self.run + "/gate-review.json",
                                           "sha256": sha256_hex(report.read_bytes())})
        modified = report.stat().st_mtime_ns
        repeated = self.invoke()
        self.assertEqual(repeated.returncode, 0, repeated.stderr + repeated.stdout)
        self.assertEqual(json.loads(repeated.stdout), envelope)
        self.assertEqual(report.stat().st_mtime_ns, modified)
        self.assertEqual(sha256_hex((self.root / "cs2-review.json").read_bytes()), sentinel["sha256"])
        self.assertFalse((self.root / self.run / "handoff.json").exists())

    def test_global_discovery_cannot_replace_an_explicit_run(self):
        other_path, other = self.request_for(".img2/cs2-terminal/run-" + "b" * 32)
        locator = ".img2/cs2-terminal/gate-request.json"
        self.fixture.put(locator, other)
        explicit = self.invoke()
        self.assertEqual(explicit.returncode, 0, explicit.stderr + explicit.stdout)
        self.assertEqual(json.loads(explicit.stdout)["evidence"]["request"]["path"], self.path)
        discovered = self.invoke(locator)
        self.assertEqual(discovered.returncode, 0, discovered.stderr + discovered.stdout)
        self.assertEqual(json.loads(discovered.stdout)["evidence"]["request"]["path"], other_path)
        self.assertTrue((self.root / self.run / "gate-review.json").exists())

    def test_unknown_schema_version_types_and_fields_fail_closed(self):
        variants = [dict(self.request, version=value) for value in (2, True, 1.0, "1")]
        variants += [dict(self.request, kind="unknown"), dict(self.request, authority=True)]
        for request in variants:
            with self.subTest(request=request):
                self.fixture.put(self.path, request)
                self.refuse()
        raw = serialize_json(self.request).replace(b'"version": 1,', b'"version": 1, "version": 1,')
        self.fixture.put(self.path, raw)
        self.refuse()

    def test_descriptor_parent_and_all_evidence_must_name_one_canonical_run(self):
        other = ".img2/cs2-terminal/run-" + "b" * 32
        other_path, other_request = self.request_for(other)
        cases = [
            (self.path, dict(self.request, scene=other_request["scene"])),
            (other_path, self.request),
            (".img2/cs2-terminal/arbitrary.json", self.request),
            (".img2/cs2-terminal/run-" + "A" * 32 + "/gate-request.json", self.request),
        ]
        for path, request in cases:
            with self.subTest(path=path):
                self.fixture.put(path, request)
                self.refuse(path)
        for unsafe in ("../inputs.json", str(self.root / self.run / "inputs.json"), self.run + "/other.json"):
            with self.subTest(unsafe=unsafe):
                request = dict(self.request, inputs=dict(self.request["inputs"], path=unsafe))
                self.fixture.put(self.path, request)
                self.refuse()

    def test_stale_bound_inputs_scene_or_delivery_refuse(self):
        for role in ("inputs", "scene"):
            with self.subTest(role=role):
                path = self.root / self.request[role]["path"]
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                self.refuse()
                path.write_bytes(original)
        (self.root / self.fixture.delivery["path"]).write_bytes(b"changed-lantern")
        self.refuse()

    def test_discovery_requires_matching_immutable_run_descriptor(self):
        locator = ".img2/cs2-terminal/gate-request.json"
        self.fixture.put(locator, self.request)
        (self.root / self.path).unlink()
        self.refuse(locator)
        self.fixture.put(self.path, dict(self.request, version=2))
        self.refuse(locator)

    def test_symlink_inputs_request_or_report_never_follow_targets(self):
        locator = ".img2/cs2-terminal/gate-request.json"
        self.fixture.put(locator, self.request)
        for relative in (self.request["inputs"]["path"], self.path, locator, self.run + "/gate-review.json"):
            with self.subTest(relative=relative):
                target = self.root / relative
                original = target.read_bytes() if target.exists() else None
                if target.exists():
                    target.unlink()
                outside = self.root / "owned-symlink-target"
                outside.write_bytes(original or b"preserve-owned-target")
                saved = outside.read_bytes()
                target.symlink_to(outside)
                self.refuse(locator if relative == locator else None)
                self.assertEqual(outside.read_bytes(), saved)
                target.unlink()
                if original is not None:
                    target.write_bytes(original)

    def test_existing_different_report_is_not_overwritten(self):
        ref = self.fixture.put(self.run + "/gate-review.json", {"prior": "must-preserve"})
        self.refuse()
        self.assertEqual(sha256_hex((self.root / ref["path"]).read_bytes()), ref["sha256"])

    def test_request_mode_refuses_authored_metrics_output_controls_and_old_mode(self):
        for arguments in (("--manifest", "authored.json"), ("--metrics", "authored.json"),
                          ("--allow-deferrals",), ("--scene", "caller-scene.json"),
                          ("--out", "caller-report.json"), ("--prepare-scene",),
                          ("--terminal-inputs", "legacy.json")):
            with self.subTest(arguments=arguments):
                self.refuse(None, *arguments)
        legacy = subprocess.run([sys.executable, str(ROOT / "tools/cs2_review.py"),
                                 "--terminal-inputs", "legacy.json", "--scene", "legacy-scene.json",
                                 "--out", "legacy-report.json"], cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(legacy.returncode, 2)
        self.assertFalse((self.root / "caller-report.json").exists())

    def test_rebound_scene_cannot_lower_the_reconstructed_policy(self):
        scenes = [
            dict(self.replay["scene"], thresholds={key: 0 for key in self.replay["scene"]["thresholds"]}),
            dict(self.replay["scene"], version=True),
        ]
        for scene in scenes:
            with self.subTest(scene=scene):
                changed = self.fixture.put(self.run + "/scene.json", scene)
                self.fixture.put(self.path, dict(self.request, scene=changed))
                self.refuse()
                self.assertFalse((self.root / self.run / "gate-review.json").exists())

    def test_measured_rejection_has_exact_report_and_no_acceptance(self):
        capture_ref = self.fixture.inputs["materialCaptures"][1]
        capture = json.loads((self.root / capture_ref["path"]).read_text())
        raw = lantern_png(32)
        capture["screenshot"] = dict(self.fixture.put(capture["screenshot"]["path"], raw),
                                     width=40, height=40, byteLength=len(raw))
        self.fixture.inputs["materialCaptures"][1] = self.fixture.put(capture_ref["path"], capture)
        self.replay = reproduce_terminal(self.root, inputs=self.fixture.inputs)
        self.path, self.request = self.request_for(self.run)
        result = self.invoke()
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["status"], "fail")
        self.assertIn("finishMaterialResponse", envelope["reasons"])
        self.assertEqual(envelope["evidence"]["verdict"], "reject")
        self.assertIs(envelope["evidence"]["terminalAuthority"], False)
        self.assertEqual((self.root / self.run / "gate-review.json").read_bytes(),
                         serialize_json(self.replay["report"]))

    def test_nonregular_request_evidence_and_report_refuse(self):
        for relative in (self.path, self.request["inputs"]["path"], self.request["scene"]["path"],
                         self.run + "/gate-review.json"):
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes() if path.exists() else None
                if path.exists():
                    path.unlink()
                path.mkdir()
                self.refuse()
                path.rmdir()
                if original is not None:
                    path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
