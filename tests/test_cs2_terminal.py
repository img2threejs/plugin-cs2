"""Synthetic measurement regressions, NOT authenticated expert or renderer evidence."""
import json
import os
import shlex
import subprocess
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import test_cs2_measure as fixture
from cs2_evidence import EvidenceError, serialize_json
from cs2_terminal import finalize_terminal, produce_terminal, reproduce_terminal
from cs2_review import main as review_main
from contextlib import redirect_stdout
from io import StringIO


def pixels(shade):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = []
    for y in range(40):
        row = bytearray()
        for x in range(40):
            color = shade if 10 <= x < 24 and 7 <= y < 33 else 240
            row.extend((color, color, color))
        rows.append(b"\0" + bytes(row))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 40, 40, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


class TerminalMeasurements(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.Cs2MeasureTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.put = self.fixture.put
        self.reference = self.put("reference.png", pixels(32))
        self.configs = []
        for index in range(3):
            path = f"capture-{index}.json"
            capture = json.loads((self.root / path).read_text())
            config = json.loads((self.root / capture["config"]["path"]).read_text())
            config.update(transform={"position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
                          lighting={"ambient": {"color": 16777215, "intensity": 1}}, background=15790320)
            config_ref = self.put(capture["config"]["path"], config)
            self.configs.append(config_ref)
            capture["config"] = config_ref
            if index == 0:
                raw = pixels(32)
                capture["screenshot"] = dict(self.put("shot-0.png", raw), width=40, height=40, byteLength=len(raw))
            self.put(path, capture)
        self.material_views, self.material_captures = [], []
        for index, shade in enumerate((32, 80)):
            source = self.put(f"material-source-{index}.png", pixels(shade))
            config = json.loads((self.root / self.configs[0]["path"]).read_text())
            config["lighting"]["ambient"]["intensity"] = index + 1
            config["viewId"] = f"material-{index}"
            config_ref = self.put(f"material-config-{index}.json", config)
            self.material_views.append({"source": source, "config": config_ref})
            capture = json.loads((self.root / "capture-0.json").read_text())
            capture.update(viewId=config["viewId"], config=config_ref)
            renderer = json.loads((self.root / capture["renderer"]["path"]).read_text())
            capture["renderer"] = self.put(f"material-renderer-{index}.json", renderer)
            raw = pixels(shade)
            capture["screenshot"] = dict(self.put(f"material-shot-{index}.png", raw), width=40, height=40, byteLength=len(raw))
            self.material_captures.append(self.put(f"material-capture-{index}.json", capture))
        self.sources = {"reference": self.reference,
                        "regions": [{"id": "paint", "bounds": [.3, .25, .5, .7]}],
                        "criticalFeatures": [{"id": "visible-detail", "bounds": [.3, .25, .5, .7]}],
                        "materialViews": self.material_views}
        self.inputs = {"intake": self.bound("intake.json"), "classification": self.bound("classification.json"),
                       "artifact": self.bound("artifact.json"), "delivery": self.bound("model.glb"),
                       "sources": self.put("sources.json", self.sources), "configs": self.configs,
                       "captures": [self.bound(path) for path in self.fixture.captures],
                       "materialCaptures": self.material_captures, "passId": "terminal"}

    def bound(self, path):
        import hashlib
        return {"path": path, "sha256": hashlib.sha256((self.root / path).read_bytes()).hexdigest()}

    def test_equal_pixels_are_measurable_not_capture_fraud(self):
        result = reproduce_terminal(self.root, inputs=self.inputs)
        self.assertEqual(result["report"]["verdict"], "pass")
        self.assertEqual(result["metrics"]["silhouetteIoU"], 1)
        self.assertEqual(result["metrics"]["finishMaterialResponse"], 1)
        self.assertEqual(result["context"]["authority"], "none-replay-only")
        self.assertIn("not proven asset identity", result["metrics"]["measurementScope"])

    def test_real_material_response_failure_is_not_replaced_by_confidence(self):
        cap = json.loads((self.root / "material-capture-1.json").read_text())
        raw = pixels(32)
        cap["screenshot"] = dict(self.put("material-shot-1.png", raw), width=40, height=40, byteLength=len(raw))
        self.inputs["materialCaptures"][1] = self.put("material-capture-1.json", cap)
        result = reproduce_terminal(self.root, inputs=self.inputs)
        self.assertEqual(result["metrics"]["finishMaterialResponse"], 0)
        self.assertIn("finishMaterialResponse", result["report"]["failedGates"])

    def test_missing_annotations_report_exact_field(self):
        del self.sources["regions"]
        self.inputs["sources"] = self.put("sources.json", self.sources)
        with self.assertRaises(EvidenceError) as caught:
            reproduce_terminal(self.root, inputs=self.inputs)
        self.assertEqual(caught.exception.reason_code, "terminal-input-missing")
        self.assertIn("regions", caught.exception.detail)

    def test_unmeasurable_material_response_is_not_a_passing_default(self):
        self.sources["materialViews"][1]["source"] = self.material_views[0]["source"]
        self.inputs["sources"] = self.put("sources.json", self.sources)
        with self.assertRaises(EvidenceError) as caught:
            reproduce_terminal(self.root, inputs=self.inputs)
        self.assertEqual(caught.exception.reason_code, "material-response-unmeasurable")

    def gate_request(self, result):
        run = ".img2/cs2-terminal/run-" + "a" * 32
        (self.root / run).mkdir(parents=True)
        inputs = self.put(run + "/inputs.json", self.inputs)
        scene = self.put(run + "/scene.json", result["scene"])
        request = {"kind": "img2.cs2-terminal-request", "version": 1, "inputs": inputs, "scene": scene}
        path = run + "/gate-request.json"
        self.put(path, request)
        return path, request

    def test_gate_replays_actual_workspace_and_rejects_changed_scene(self):
        result = reproduce_terminal(self.root, inputs=self.inputs)
        request_path, request = self.gate_request(result)
        args = ["--workspace", str(self.root), "--terminal-request", request_path]
        output = StringIO()
        with redirect_stdout(output):
            code = review_main(args)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["evidence"]["artifact"], self.inputs["artifact"])
        result["scene"]["thresholds"]["finishMaterialResponse"] = 0
        request["scene"] = self.put(request["scene"]["path"], result["scene"])
        self.put(request_path, request)
        with redirect_stdout(StringIO()):
            self.assertEqual(review_main(args), 2)

    def test_literal_declared_gate_rejects_stale_synthetic_evidence(self):
        # This executes the declaration, but does not authenticate a base host.
        plugin = Path(__file__).resolve().parents[1]
        result = reproduce_terminal(self.root, inputs=self.inputs)
        _, request = self.gate_request(result)
        self.put(".img2/cs2-terminal/gate-request.json", request)
        gate = json.loads((plugin / "gates.json").read_text())[0]
        command = shlex.split(gate["command"].format(plugin_dir=plugin))
        home = self.root / "home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
        valid = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(valid.returncode, 0, valid.stderr + valid.stdout)
        self.assertEqual(json.loads(valid.stdout)["status"], "pass")
        (self.root / "sources.json").write_bytes(serialize_json({}))
        stale = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(stale.returncode, 2)
        self.assertEqual(json.loads(stale.stdout)["status"], "error")
        self.assertIn("input-digest-mismatch", stale.stderr)

    def test_host_refusal_cannot_publish_a_terminal_handoff(self):
        class RefusingHost:
            def verify_classification(self, *args, **kwargs):
                raise ValueError("unauthenticated classification")
        with self.assertRaisesRegex(ValueError, "unauthenticated classification"):
            produce_terminal(self.root, inputs=self.inputs, host=RefusingHost())
        self.assertFalse((self.root / ".img2/cs2-terminal/handoff.json").exists())

    def test_stale_sources_refused_before_host_capture(self):
        (self.root / "sources.json").write_bytes(serialize_json({}))
        with self.assertRaises(EvidenceError) as caught:
            produce_terminal(self.root, inputs=self.inputs, host=object())
        self.assertEqual(caught.exception.reason_code, "input-digest-mismatch")

    def test_producer_calls_host_before_handoff_and_rechecks_review(self):
        # A test double exercises sequencing only; it is NOT base authentication.
        case, calls = self, []
        class FixtureHost:
            def verify_classification(self, workspace, **kwargs):
                calls.append("classification")
            def verify_sources(self, workspace, **kwargs):
                calls.append("sources")
            def capture(self, workspace, *, config, **kwargs):
                calls.append(config["viewId"])
                index = int(config["viewId"].rsplit("-", 1)[1])
                return case.inputs["materialCaptures"][index] if config["viewId"].startswith("material-") else case.inputs["captures"][index]
            def verify_quality(self, workspace, *, context):
                calls.append("quality")
                case.assertEqual(context["artifact"], case.inputs["artifact"])
                case.assertIn("region:paint", context["requiredChecks"])
        handoff = produce_terminal(self.root, inputs=self.inputs, host=FixtureHost())
        self.assertEqual(handoff["status"], "host-reviewed")
        self.assertFalse(handoff["deliverable"])
        self.assertEqual(calls, ["classification", "sources", "view-0", "view-1", "view-2",
                                 "material-0", "material-1", "quality"])
        self.assertTrue((self.root / ".img2/cs2-terminal/handoff.json").is_file())

    def test_changed_input_after_host_review_cannot_publish_handoff(self):
        case = self
        class MutatingFixtureHost:
            def verify_classification(self, workspace, **kwargs):
                pass
            def verify_sources(self, workspace, **kwargs):
                pass
            def capture(self, workspace, *, config, **kwargs):
                index = int(config["viewId"].rsplit("-", 1)[1])
                return case.inputs["materialCaptures"][index] if config["viewId"].startswith("material-") else case.inputs["captures"][index]
            def verify_quality(self, workspace, *, context):
                (case.root / "sources.json").write_bytes(serialize_json({}))
        with self.assertRaises(EvidenceError):
            produce_terminal(self.root, inputs=self.inputs, host=MutatingFixtureHost())
        self.assertFalse((self.root / ".img2/cs2-terminal/handoff.json").exists())

    def test_finalization_resumes_exact_review_context_without_recapture(self):
        case = self
        class DeferredReviewHost:
            ready = False
            captures = 0
            def verify_classification(self, workspace, **kwargs):
                pass
            def verify_sources(self, workspace, **kwargs):
                pass
            def capture(self, workspace, *, config, **kwargs):
                self.captures += 1
                index = int(config["viewId"].rsplit("-", 1)[1])
                return case.inputs["materialCaptures"][index] if config["viewId"].startswith("material-") else case.inputs["captures"][index]
            def verify_quality(self, workspace, *, context):
                if not self.ready:
                    raise ValueError("authenticated review missing")
        host = DeferredReviewHost()
        with self.assertRaisesRegex(ValueError, "authenticated review missing"):
            produce_terminal(self.root, inputs=self.inputs, host=host)
        persisted = json.loads((self.root / ".img2/cs2-terminal/inputs.json").read_text())
        host.ready = True
        result = finalize_terminal(self.root, inputs=persisted, host=host)
        self.assertEqual(result["status"], "host-reviewed")
        self.assertEqual(host.captures, 5)
