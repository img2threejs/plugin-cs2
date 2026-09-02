#!/usr/bin/env python3
"""Emit the spec-augmentation artifact the base pipeline pulls.

The base authors a skeleton and lets the agent infer the shape from the reference. When this plugin
is installed, this step publishes an authoritative CS2 recipe instead, and the base merges it.

The base pulls; this never writes into the base's spec (PLUGIN_CONTRACT.md section 14). The artifact
is partitioned so the base can apply different rules to different parts:

    specSections     wholesale spec sections this domain authors (component tree, materials, ...)
    assessmentPatch  fields merged into preSpecAssessment
    qualityFloors    numbers and tiers merged RAISE-ONLY by the base -- a plugin must never be able
                     to lower the bar it was installed to raise
    provenance       which provider and version proposed all of the above
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cs2_spec_template import apply_cs2_template, apply_cs2_manifest_evidence  # noqa: E402

ARTIFACT_KIND = "spec-augmentation-v1"
# Read from plugin.json so the provenance stamp cannot drift from the released version -- it did
# once: 0.1.1 shipped with a hardcoded "0.1.0" here, making fixed artifacts indistinguishable from
# broken ones by the very field that exists to attribute them.
PLUGIN_VERSION = json.loads((Path(__file__).resolve().parent.parent / "plugin.json").read_text(encoding="utf-8"))["version"]

# Keys the BASE owns. Everything else this template writes is domain territory and ships as an
# opaque section. Deliberately a deny-list, not an allow-list: an allow-list would have to enumerate
# every domain's sections (this one writes cs2Finish and envMapIntensity; the character domain writes
# rig, buildPasses and sculptPipeline), which is how the base ends up knowing its domains by name
# again. A third domain nobody has written yet works under this rule without changing anything.
BASE_OWNED = ("qualityContract", "preSpecAssessment", "pipelineRouting", "sourceImage", "targetName", "localSpecSearch")
ASSESSMENT_FIELDS = ("objectClass", "complexity", "specDepthDecision", "detailInventory")


def build(args: argparse.Namespace) -> dict[str, Any]:
    manifest: dict[str, Any] | None = None
    if args.manifest:
        manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")

    scratch: dict[str, Any] = {}
    apply_cs2_template(
        scratch,
        args.finish_style,
        skin_name=args.skin_name,
        vision_finish_style=args.vision_finish_style,
        vision_confidence=args.vision_confidence,
        float_value=args.cs2_float,
        paint_seed=args.paint_seed,
        environment_available=not args.no_environment,
        item_family=str(manifest.get("itemFamily", "knife")) if manifest else args.item_family,
        subtype=(str(manifest["subtype"]) if manifest and manifest.get("subtype") else args.subtype),
    )
    if manifest:
        apply_cs2_manifest_evidence(scratch, manifest)

    pre = scratch.get("preSpecAssessment", {})
    contract = scratch.get("qualityContract", {})
    assessment_patch = {k: pre[k] for k in ASSESSMENT_FIELDS if k in pre}
    # The domain marker is set by the base's own domain resolution, never proposed by an artifact.
    assessment_patch.get("objectClass", {}).pop("domain", None)
    if "detailInventory" in assessment_patch:
        # The floor travels through qualityFloors alone. Sending it through the patch as well
        # let the unclamped copy win before the base guarded both partitions (PR #106 review,
        # finding 1). Copied, not popped: the comprehension above shares dicts with `pre`, and
        # the floors block below still reads pre["detailInventory"]["targetMinDetails"].
        assessment_patch["detailInventory"] = {
            k: v for k, v in assessment_patch["detailInventory"].items() if k != "targetMinDetails"
        }

    floors: dict[str, Any] = {}
    if "qualityBar" in contract:
        floors["qualityBar"] = contract["qualityBar"]
    if "minimumSpecDepth" in contract:
        floors["minimumSpecDepth"] = contract["minimumSpecDepth"]
    if "targetMinDetails" in pre.get("detailInventory", {}):
        floors["targetMinDetails"] = pre["detailInventory"]["targetMinDetails"]

    return {
        "kind": ARTIFACT_KIND,
        "provenance": {"provider": "cs2", "version": PLUGIN_VERSION},
        "specSections": {k: v for k, v in scratch.items() if k not in BASE_OWNED},
        "assessmentPatch": assessment_patch,
        "qualityFloors": floors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="write the augmentation artifact here")
    parser.add_argument("--manifest", type=Path, help="validated cs2-intake.json")
    parser.add_argument("--finish-style", default=None)
    parser.add_argument("--skin-name", default=None)
    parser.add_argument("--vision-finish-style", default=None)
    parser.add_argument("--vision-confidence", type=float, default=None)
    parser.add_argument("--cs2-float", type=float, default=None)
    parser.add_argument("--paint-seed", type=int, default=None)
    parser.add_argument("--no-environment", action="store_true")
    parser.add_argument("--item-family", default="knife")
    parser.add_argument("--subtype", default=None)
    args = parser.parse_args(argv)

    artifact = build(args)
    out = args.out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"kind": artifact["kind"], "out": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
