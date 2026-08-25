"""The CS2 finish recipe.

These assertions came from the base skill's test_pipeline.py, where they drove the whole pipeline
through `new_sculpt_spec.py --cs2`. That flag is gone: the base authors a skeleton and pulls this
domain's recipe from a spec-augmentation artifact instead. What they actually pinned -- the PBR
response of each finish family, how float and paint seed move wear and pattern placement, and the
identity precedence rules -- is this plugin's behaviour, so it is tested here, directly.

The TypeScript-emission half of the originals stays with the base: `generate_threejs_factory` is base
code and has its own coverage there.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cs2_spec_template import apply_cs2_template  # noqa: E402


def template(**kwargs):
    spec: dict = {}
    kwargs.setdefault("item_family", "knife")
    style = kwargs.pop("finish_style", None)
    apply_cs2_template(spec, style, **kwargs)
    return spec


def finish_material(spec):
    return next(m for m in spec["materials"] if m["id"] == "skin-finish")


class FinishResponse(unittest.TestCase):
    def test_an_anodized_finish_is_view_dependent_and_needs_an_environment(self) -> None:
        spec = template(finish_style="anodized-multicolored")
        finish = finish_material(spec)
        self.assertGreaterEqual(finish["metalness"]["base"], 0.9)
        self.assertLessEqual(finish["roughness"]["base"], 0.15)
        self.assertGreaterEqual(spec["envMapIntensity"], 1.5)
        self.assertTrue(finish["needsEnvironment"])
        self.assertTrue(spec["cs2Finish"]["viewDependent"])

    def test_a_view_dependent_finish_is_refused_without_an_environment(self) -> None:
        # A view-dependent finish rendered with no environment reads as flat grey, so the template
        # records the conflict rather than emitting a finish that cannot look right.
        spec = template(finish_style="anodized-multicolored", environment_available=False)
        unknowns = spec.get("preSpecAssessment", {}).get("unknownsToResolveBeforeImplementation", [])
        blob = " ".join(str(u) for u in unknowns) + " " + str(spec.get("cs2Finish", {}))
        self.assertIn("environment", blob.lower())


class QualityFloors(unittest.TestCase):
    def test_cs2_is_held_to_the_top_fidelity_bar(self) -> None:
        spec = template()
        pre = spec["preSpecAssessment"]
        self.assertEqual(pre["complexity"]["tier"], "ultra-complex")
        self.assertEqual(pre["detailInventory"]["targetMinDetails"], 16)
        self.assertEqual(spec["qualityContract"]["qualityBar"], "ultra-complex")
        self.assertEqual(spec["qualityContract"]["minimumSpecDepth"]["macroComponents"], 5)


class FloatAndPaintSeed(unittest.TestCase):
    def test_a_higher_float_produces_more_wear(self) -> None:
        low = finish_material(template(finish_style="anodized", float_value=0.01))
        high = finish_material(template(finish_style="anodized", float_value=0.90))
        self.assertNotEqual(low.get("wear"), high.get("wear"),
                            "float must move the wear treatment, or it is not being read")

    def test_paint_seed_moves_pattern_placement_deterministically(self) -> None:
        # The seed lands on the finish material's patternPlacement, not on the cs2Finish summary.
        a = finish_material(template(finish_style="anodized-multicolored", paint_seed=1))["patternPlacement"]
        b = finish_material(template(finish_style="anodized-multicolored", paint_seed=2))["patternPlacement"]
        again = finish_material(template(finish_style="anodized-multicolored", paint_seed=1))["patternPlacement"]
        self.assertEqual(a, again, "the same seed must give the same placement")
        self.assertNotEqual(a, b, "a different seed must move the placement")
        self.assertEqual(a["paintSeed"], 1)


class IdentityPrecedence(unittest.TestCase):
    def test_an_explicit_finish_style_beats_a_skin_name_hint(self) -> None:
        spec = template(finish_style="patina", skin_name="Karambit | Doppler")
        self.assertEqual(spec["cs2Finish"]["finishStyle"], "patina")

    def test_a_skin_name_resolves_a_style_when_none_is_explicit(self) -> None:
        spec = template(skin_name="Karambit | Doppler")
        self.assertEqual(spec["cs2Finish"]["finishStyle"], "anodized-multicolored")


if __name__ == "__main__":
    unittest.main()
