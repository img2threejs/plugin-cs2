"""Synthetic capture-integrity tests; no host or renderer authenticity is claimed."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from cs2_manifest import build_classification_record


def png(left):
    rows = []
    for y in range(40):
        row = bytearray()
        for x in range(40):
            color = 32 if left <= x < left + 14 and 7 <= y < 33 else 240
            row.extend((color, color, color))
        rows.append(b"\0" + bytes(row))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 40, 40, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


class Cs2MeasureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.reference = self.put("reference.png", png(10))
        classification = build_classification_record("knife", "karambit", .98, ["fixture"], provider="offline-fixture")
        self.put("classification.json", classification)
        self.put("intake.json", {"state": "proceed", "itemFamily": classification["itemFamily"],
                                 "subtype": classification["subtype"], "classification": classification,
                                 "sourceViews": [{"role": "reference", **self.reference}]})
        delivery = self.put("model.glb", b"fixture model bytes; not a proven GLB")
        self.artifact = self.put("artifact.json", {"objectId": "subject", "outputKind": "3d-object", "files": [delivery]})
        viewport = {"width": 40, "height": 40, "devicePixelRatio": 1}
        frame = {"units": "m", "up": "+Y", "forward": "+Z"}
        self.captures = []
        for index, left in enumerate((11, 13, 15)):
            camera = {"position": [index, 0, 3]}
            rendered_camera = dict(camera, aspect=1.0)
            config = self.put(f"config-{index}.json", {"viewId": f"view-{index}", "frame": frame,
                              "viewport": viewport, "camera": camera})
            renderer = self.put(f"renderer-{index}.json", {"runtimeReport": {"camera": rendered_camera,
                                "viewport": viewport, "frame": frame, "canvas": {"width": 40, "height": 40},
                                "renderer": {"name": "WebGLRenderer"}, "threeRevision": "fixture",
                                "deliverySha256": delivery["sha256"]}})
            pixels = png(left)
            screenshot = dict(self.put(f"shot-{index}.png", pixels), width=40, height=40, byteLength=len(pixels))
            self.put(f"capture-{index}.json", {"kind": "img2.delivered-glb-capture", "version": 1,
                "status": "captured", "artifact": self.artifact, "delivery": delivery,
                "viewId": f"view-{index}", "camera": rendered_camera, "frame": frame, "viewport": viewport,
                "renderer": renderer, "config": config, "screenshot": screenshot})
            self.captures.append(f"capture-{index}.json")

    def put(self, path, data):
        raw = data if isinstance(data, bytes) else json.dumps(data, sort_keys=True).encode()
        (self.root / path).write_bytes(raw)
        return {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}

    def run_cli(self):
        args = [sys.executable, str(TOOLS / "cs2_measure.py"), "--workspace", str(self.root),
                "--intake", "intake.json", "--classification", "classification.json", "--artifact", "artifact.json"]
        for capture in self.captures:
            args.extend(["--capture", capture])
        return subprocess.run(args, capture_output=True, text=True)

    def test_measures_pixels_without_semantic_or_delivery_claim(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        output = json.loads(result.stdout)
        self.assertFalse(output["deliverable"])
        self.assertGreater(output["referenceView"]["silhouetteIoU"], 0)
        self.assertLess(output["referenceView"]["silhouetteIoU"], 1)
        self.assertNotIn("finishMaterialResponse", output)
        self.assertNotIn("identityDetail", output)

    def test_changed_render_changes_measured_silhouette(self):
        first = json.loads(self.run_cli().stdout)["referenceView"]["silhouetteIoU"]
        pixels = png(18)
        screenshot = dict(self.put("shot-0.png", pixels), width=40, height=40, byteLength=len(pixels))
        capture = json.loads((self.root / "capture-0.json").read_text())
        capture["screenshot"] = screenshot
        self.put("capture-0.json", capture)
        second_result = self.run_cli()
        self.assertEqual(second_result.returncode, 0, second_result.stderr + second_result.stdout)
        second = json.loads(second_result.stdout)["referenceView"]["silhouetteIoU"]
        self.assertLess(second, first)

    def test_tampered_capture_is_refused(self):
        (self.root / "shot-0.png").write_bytes(png(18))
        result = self.run_cli()
        self.assertEqual(result.returncode, 4)
        self.assertEqual(json.loads(result.stdout)["reasonCode"], "input-digest-mismatch")

    def test_identical_pixels_do_not_prove_a_capture_is_invalid(self):
        pixels = (self.root / "reference.png").read_bytes()
        screenshot = dict(self.put("shot-0.png", pixels), width=40, height=40, byteLength=len(pixels))
        capture = json.loads((self.root / "capture-0.json").read_text())
        capture["screenshot"] = screenshot
        self.put("capture-0.json", capture)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["referenceView"]["silhouetteIoU"], 1.0)

    def test_same_camera_is_refused(self):
        path = self.root / "capture-1.json"
        capture = json.loads(path.read_text())
        capture["camera"] = {"position": [0, 0, 3], "aspect": 1.0}
        self.put("capture-1.json", capture)
        result = self.run_cli()
        self.assertEqual(result.returncode, 5)
        self.assertEqual(json.loads(result.stdout)["reasonCode"], "capture-viewpoint-mismatch")

    def test_consistent_repeated_camera_is_refused_as_duplicate_view(self):
        capture = json.loads((self.root / "capture-1.json").read_text())
        config = json.loads((self.root / capture["config"]["path"]).read_text())
        renderer = json.loads((self.root / capture["renderer"]["path"]).read_text())
        config["camera"]["position"] = [0, 0, 3]
        renderer["runtimeReport"]["camera"]["position"] = [0, 0, 3]
        capture["camera"]["position"] = [0, 0, 3]
        capture["config"] = self.put(capture["config"]["path"], config)
        capture["renderer"] = self.put(capture["renderer"]["path"], renderer)
        self.put("capture-1.json", capture)
        result = self.run_cli()
        self.assertEqual(result.returncode, 5)
        self.assertEqual(json.loads(result.stdout)["reasonCode"], "orbit-view-not-distinct")
