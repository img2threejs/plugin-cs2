#!/usr/bin/env python3
"""CS2 spec template: the finish, material and component recipe for a CS2 skin.

Moved verbatim from the base skill's forge/stage2_spec/new_sculpt_spec.py. The base pipeline authors
a skeleton and lets the agent infer the shape from the reference; this module is what a run gets
INSTEAD of that inference when the CS2 plugin is installed -- an authoritative knife component tree,
the finish/substrate material recipe, and the CS2 review targets.

_cnode and _shade_hex are small generic helpers copied alongside, because this module builds its own
component nodes and a plugin may not import forge.* (PLUGIN_CONTRACT.md section 8).
"""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

# Minimal skin-name -> finish-style hints for the identity precedence resolver. Not exhaustive
# (thousands of CS2 skins exist); a name that doesn't match falls through to vision/default.
SKIN_NAME_FINISH_HINTS = {
    "doppler": "anodized-multicolored", "gamma doppler": "anodized-multicolored",
    "marble fade": "anodized-multicolored", "fade": "anodized",
    "damascus": "patina", "case hardened": "patina",
    "hydrographic": "hydrographic", "hydro dip": "hydrographic",
    "urban": "spray-paint", "spray": "spray-paint",
    "custom": "custom-paint-job", "gunsmith": "gunsmith",
}

def _cnode(cid, name, primitive, parent, position, scale,
           material="skin", role="body", level="meso", rotation=(0, 0, 0),
           importance=0.7, sockets=None, local_features=None, anim_role="static",
           pivot_mode="center", evidence=None, topology_class="assembled-solid",
           topology_rationale=None, attachment=None, sdf=None, transform_scale=None):
    """Build a full schema-valid componentTree node with humanoid-friendly defaults.

    `attachment` (optional) supplies a validate_sculpt_spec.py-complete attachment contract
    (parentSocket, localStart/localEnd, contactType, baseRadius/endRadius, embedDepth,
    gapTolerance). When localStart/localEnd form a non-degenerate segment, the factory's
    makeAttachmentEndpoint() auto-builds a tapered cylinder spanning them and IGNORES this
    node's own transform/scale for geometry -- so `position`/`scale` above still populate the
    schema's transform/dimensions fields (informational + a render fallback) but the actual
    mesh is driven by the attachment endpoints. `sdf` (optional) supplies a
    geometryDescriptor.sdf block for an implicit/concave part (e.g. a recessed eye socket via
    `subtract`); when given, topologyClass is forced to 'implicit' and transform.scale is
    forced to identity since the SDF primitives already encode real world-unit sizes.
    """
    if topology_rationale is None:
        topology_rationale = (
            f"{name} is a discrete primitive body part assembled onto the humanoid rig, "
            f"not a continuous sculpt or shell."
        )
    if sdf is not None:
        topology_class = "implicit"
        transform_scale = (1.0, 1.0, 1.0)
    node = {
        "id": cid, "name": name, "level": level, "role": role,
        "importance": importance, "confidence": 0.8, "primitive": primitive,
        "topologyClass": topology_class,
        "topologyRationale": topology_rationale,
        "geometryDescriptor": {
            "topologyIntent": "stylized character part",
            "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1},
            "deformationStack": [], "uvStrategy": "generated procedural coordinates",
            "normalStrategy": "smooth vertex normals",
        },
        "parent": parent, "attachment": attachment,
        "dimensions": {"width": float(scale[0]), "height": float(scale[1]),
                       "depth": float(scale[2]), "units": "relative", "confidence": 0.8},
        "transform": {"position": list(position), "rotation": list(rotation),
                      "scale": list(transform_scale if transform_scale is not None else scale)},
        "actionProfile": {
            "animationRole": anim_role,
            "pivot": {"mode": pivot_mode, "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.7},
            "transformChannels": {"translate": True, "rotate": True, "scale": True,
                                  "bend": False, "twist": False, "detach": False,
                                  "visibility": True, "materialState": False},
            "sockets": sockets or [],
            "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1],
                         "isTrigger": False, "notes": "box proxy"},
            "constraints": [],
            "destruction": {"breakable": False, "fractureGroup": cid, "seamRefs": [],
                            "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": material},
        },
        "material": material, "materialLayers": [material], "deformations": [], "joints": [],
        "seams": [], "localFeatures": local_features or [],
        "surfaceDetail": {"macroRoughness": 0.0, "microRoughness": 0.0, "bumpAmplitude": 0.0,
                          "normalPattern": "", "displacementPattern": "", "occlusionPattern": "",
                          "edgeWearPattern": "", "notes": ""},
        "evidenceRefs": evidence or ["full-object"], "details": [], "fidelityTier": "blockout",
    }
    if sdf is not None:
        node["geometryDescriptor"]["sdf"] = sdf
    return node
def _shade_hex(hex_color: str, factor: float) -> str:
    """Return a slightly darker/lighter shade of a #RRGGBB color (factor<1 darker)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, round(c * factor))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"
CS2_DOMAIN_ID = "cs2"
CS2_FINISH_STYLES = [
    "solid", "hydrographic", "anodized", "spray-paint",
    "anodized-multicolored", "custom-paint-job", "patina", "gunsmith",
]
CS2_FINISH_PROFILES = {
    "solid":                 {"baseColor": "#7a4b2b", "metalness": 0.15, "roughness": 0.55, "clearcoat": 0.0, "env": 0.9, "viewDependent": False,
                              "pattern": "flat", "bands": [
                                  {"id": "macro", "frequency": 1.0, "amplitude": 0.05, "role": "near-uniform lacquer color"},
                                  {"id": "meso", "frequency": 8.0, "amplitude": 0.03, "role": "faint brush-out streaks"},
                                  {"id": "micro", "frequency": 40.0, "amplitude": 0.02, "role": "edge-wear scratches under grazing light"},
                              ]},
    "hydrographic":          {"baseColor": "#5b6357", "metalness": 0.20, "roughness": 0.50, "clearcoat": 0.10, "env": 1.0, "viewDependent": False,
                              "pattern": "swirl", "bands": [
                                  {"id": "macro", "frequency": 3.0, "amplitude": 0.5, "role": "dip-film swirl distortion"},
                                  {"id": "meso", "frequency": 10.0, "amplitude": 0.15, "role": "print-pattern fine detail"},
                                  {"id": "micro", "frequency": 50.0, "amplitude": 0.05, "role": "edge-wear scratches under grazing light"},
                              ]},
    "anodized":              {"baseColor": "#3a4a9a", "metalness": 0.92, "roughness": 0.12, "clearcoat": 0.30, "env": 1.8, "viewDependent": True,
                              "pattern": "brushed", "bands": [
                                  {"id": "macro", "frequency": 1.5, "amplitude": 0.1, "role": "dyed-metal color breakup"},
                                  {"id": "meso", "frequency": 20.0, "amplitude": 0.1, "role": "directional brushed-metal streaks"},
                                  {"id": "micro", "frequency": 70.0, "amplitude": 0.05, "role": "edge-wear scratches under grazing light"},
                              ]},
    "spray-paint":           {"baseColor": "#6a6a6a", "metalness": 0.10, "roughness": 0.60, "clearcoat": 0.0, "env": 0.9, "viewDependent": False,
                              "pattern": "speckle", "bands": [
                                  {"id": "macro", "frequency": 1.0, "amplitude": 0.05, "role": "matte overspray base"},
                                  {"id": "meso", "frequency": 30.0, "amplitude": 0.25, "role": "overspray speckle clusters"},
                                  {"id": "micro", "frequency": 90.0, "amplitude": 0.1, "role": "edge-wear scratches under grazing light"},
                              ]},
    "anodized-multicolored": {"baseColor": "#b0417a", "metalness": 0.95, "roughness": 0.08, "clearcoat": 0.60, "env": 2.0, "viewDependent": True,
                              "pattern": "marble", "bands": [
                                  {"id": "macro", "frequency": 2.0, "amplitude": 0.4, "role": "broad pattern/color breakup"},
                                  {"id": "meso", "frequency": 14.0, "amplitude": 0.2, "role": "brushed grain / marble swirl relief"},
                                  {"id": "micro", "frequency": 60.0, "amplitude": 0.07, "role": "edge-wear scratches under grazing light"},
                              ]},
    "custom-paint-job":      {"baseColor": "#9a2b2b", "metalness": 0.20, "roughness": 0.45, "clearcoat": 0.20, "env": 1.1, "viewDependent": False,
                              "pattern": "illustrative", "bands": [
                                  {"id": "macro", "frequency": 0.8, "amplitude": 0.6, "role": "large non-tiled artwork blocks"},
                                  {"id": "meso", "frequency": 6.0, "amplitude": 0.1, "role": "artwork edge detail"},
                                  {"id": "micro", "frequency": 40.0, "amplitude": 0.04, "role": "peel-wear scratches under grazing light"},
                              ]},
    "patina":                {"baseColor": "#7a6a3a", "metalness": 0.60, "roughness": 0.40, "clearcoat": 0.0, "env": 1.2, "viewDependent": False,
                              "pattern": "blotch", "bands": [
                                  {"id": "macro", "frequency": 1.2, "amplitude": 0.35, "role": "oxidation blotch breakup"},
                                  {"id": "meso", "frequency": 9.0, "amplitude": 0.25, "role": "hue-shift oxidation detail"},
                                  {"id": "micro", "frequency": 45.0, "amplitude": 0.1, "role": "darkened edge wear under grazing light"},
                              ]},
    "gunsmith":              {"baseColor": "#8a7a5a", "metalness": 0.70, "roughness": 0.35, "clearcoat": 0.10, "env": 1.3, "viewDependent": False,
                              "pattern": "mask-blend", "bands": [
                                  {"id": "macro", "frequency": 1.5, "amplitude": 0.3, "role": "custom-paint/patina mask blend"},
                                  {"id": "meso", "frequency": 12.0, "amplitude": 0.2, "role": "peel + oxidize transition detail"},
                                  {"id": "micro", "frequency": 55.0, "amplitude": 0.09, "role": "edge-wear scratches under grazing light"},
                              ]},
}
def _cs2_wear_mask(float_value: float | None) -> dict:
    """Map a CS2 float (0.0 Factory New .. 1.0 Battle-Scarred) to wear-mask parameters. With no
    float (image-only default) approximate a light-moderate condition from the visible reference
    instead of silently guessing -- see grimoire/build/cs2_finishes.md ('Float -> wear')."""
    if float_value is None:
        return {
            "edgeWear": 0.35, "scratches": ["approximated-light-edge-scratch"], "chips": [],
            "alphaCurve": "curvature-weighted", "aoBias": 0.3, "approximated": True,
            "notes": "No float supplied: estimated apparent condition from the reference image.",
        }
    clamped = max(0.0, min(1.0, float_value))
    return {
        "edgeWear": round(0.1 + clamped * 0.8, 3),
        "scratches": ["edge-scratch"] if clamped > 0.15 else [],
        "chips": ["edge-chip"] if clamped > 0.55 else [],
        "alphaCurve": "curvature-weighted",
        "aoBias": round(0.15 + clamped * 0.25, 3),
        "approximated": False,
        "notes": f"Wear mask derived from float={clamped}.",
    }
def _cs2_pattern_affine(paint_seed: int | None) -> dict:
    """Deterministic T2*R*S*T1 affine placement for the pattern layer, seeded by paintSeed. With
    no paintSeed (image-only default) use a fixed centered placement and report it approximated --
    never claim it matches a specific item's actual pattern (see grimoire/build/cs2_finishes.md)."""
    if paint_seed is None:
        return {
            "paintSeed": None, "affine": "T2*R*S*T1",
            "translation": [0.5, 0.5], "rotation": 0.0, "scale": [1.0, 1.0],
            "matrix": [1.0, 0.0, 0.0, 1.0, 0.5, 0.5],
            "approximated": True,
            "notes": "No paintSeed in image-first mode: deterministic default placement, reported approximated.",
        }
    rng = paint_seed & 0xFFFFFFFF
    angle = ((rng % 360) / 360.0) * 2 * math.pi
    tx = ((rng >> 8) % 1000) / 1000.0
    ty = ((rng >> 16) % 1000) / 1000.0
    scale = 0.85 + ((rng >> 24) % 30) / 100.0
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return {
        "paintSeed": paint_seed, "affine": "T2*R*S*T1",
        "translation": [round(tx, 4), round(ty, 4)], "rotation": round(angle, 4),
        "scale": [round(scale, 4), round(scale, 4)],
        "matrix": [round(cos_a * scale, 4), round(sin_a * scale, 4),
                  round(-sin_a * scale, 4), round(cos_a * scale, 4),
                  round(tx, 4), round(ty, 4)],
        "approximated": False,
        "notes": f"Deterministic placement from paintSeed={paint_seed}.",
    }
def infer_finish_style_from_skin_name(skin_name: str) -> str | None:
    lowered = skin_name.lower()
    for keyword, style in SKIN_NAME_FINISH_HINTS.items():
        if keyword in lowered:
            return style
    return None
def resolve_cs2_finish_style(
    descriptor_finish_style: str | None,
    skin_name: str | None,
    vision_finish_style: str | None,
    vision_confidence: float | None = None,
    vision_confidence_threshold: float = 0.55,
) -> tuple[str, list[str]]:
    """Identity precedence: explicit descriptor > skin name (parsed) > vision inference > default.
    A low-confidence vision read is still used (never silently dropped) but flagged. Disagreements
    between sources are reported, never silently overwritten -- see design.md 'Vision inference'."""
    conflicts: list[str] = []
    skin_inferred = infer_finish_style_from_skin_name(skin_name) if skin_name else None
    candidates: list[tuple[str, str]] = []
    if descriptor_finish_style:
        candidates.append(("descriptor", descriptor_finish_style))
    if skin_inferred:
        candidates.append(("skin name", skin_inferred))
    if vision_finish_style and (vision_confidence is None or vision_confidence >= vision_confidence_threshold):
        candidates.append(("vision", vision_finish_style))
    if len(candidates) >= 2 and len({style for _, style in candidates}) > 1:
        sources = ", ".join(f"{source}={style}" for source, style in candidates)
        conflicts.append(
            f"CS2 finish style conflict: {sources} disagree; using {candidates[0][1]!r} "
            f"({candidates[0][0]} takes precedence). Confirm before implementation."
        )
    if candidates:
        return candidates[0][1], conflicts
    if vision_finish_style:
        conflicts.append(
            f"CS2 finish style {vision_finish_style!r} inferred by vision below confidence "
            f"threshold ({vision_confidence}); confirm before implementation."
        )
        return vision_finish_style, conflicts
    return "anodized-multicolored", conflicts
def _cs2_finish_material(finish_style: str, float_value: float | None = None, paint_seed: int | None = None) -> dict:
    profile = CS2_FINISH_PROFILES[finish_style]
    base = profile["baseColor"]
    shade = _shade_hex(base, 0.8)
    bands = profile["bands"]
    return {
        "id": "skin-finish", "name": f"CS2 {finish_style} finish", "type": "standard",
        "shaderModel": "MeshPhysicalMaterial / metallic-roughness PBR",
        "baseColor": base, "color": base,
        "albedo": {"dominant": base, "secondary": [shade],
                   "samplingNotes": "Image-first: estimate from the reference; report as approximated (not the exact Valve paint texture)."},
        "colorVariation": {"palette": [base, shade], "pattern": profile["pattern"], "amplitude": bands[0]["amplitude"], "heightCorrelation": 0.25},
        "textureResolution": 1024,
        "textureProjection": {"mode": "uv", "repeat": [1.0, 1.0], "anisotropy": 8,
                              "texelDensityIntent": "Preserve stable blade-scale detail; do not stretch pattern with component scale."},
        "surfaceFrequencyBands": bands,
        "roughness": {"base": profile["roughness"], "variation": 0.06, "map": "independent-procedural-field",
                      "localResponse": "lower roughness on worn edges, higher in recesses"},
        "metalness": {"base": profile["metalness"], "variation": 0.03},
        "clearcoat": {"base": profile["clearcoat"]},
        "clearcoatRoughness": {"base": 0.12},
        "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 28.0, "space": "tangent"},
        "ambientOcclusion": {"cavityStrength": 0.3, "contactShadowBias": 0.35,
                             "notes": "Darken guard/pommel seams and engraving recesses."},
        "wear": _cs2_wear_mask(float_value),
        "envMapIntensity": profile["env"],
        "finishStyle": finish_style,
        "viewDependent": profile["viewDependent"],
        "needsEnvironment": profile["viewDependent"],
        "patternPlacement": _cs2_pattern_affine(paint_seed),
        "shaderNotes": [
            "Use MeshPhysicalMaterial: metallic-roughness with independent map channels.",
            "View-dependent finishes require scene.environment (code-generated default is fine) + ACESFilmic tonemapping in sRGB.",
            "Never bake lighting/pattern into a single flat albedo.",
        ],
        "notes": f"{finish_style} finish recipe; see grimoire/build/cs2_finishes.md.",
    }
_CS2_SUBSTRATE_BANDS = [
    {"id": "macro", "frequency": 2.0, "amplitude": 0.4, "role": "broad pattern/color breakup"},
    {"id": "meso", "frequency": 14.0, "amplitude": 0.2, "role": "brushed grain relief"},
    {"id": "micro", "frequency": 60.0, "amplitude": 0.07, "role": "edge-wear scratches under grazing light"},
]
def _cs2_substrate_material() -> dict:
    return {
        "id": "substrate", "name": "Bare metal substrate", "type": "standard",
        "shaderModel": "MeshPhysicalMaterial / metallic-roughness PBR",
        "baseColor": "#3b3b40", "color": "#3b3b40",
        "colorVariation": {"palette": ["#3b3b40", "#2b2b30"], "pattern": "flat", "amplitude": 0.05, "heightCorrelation": 0.0},
        "textureResolution": 1024,
        "textureProjection": {"mode": "uv", "repeat": [2.0, 2.0], "anisotropy": 8,
                              "texelDensityIntent": "Preserve stable metal-scale detail on exposed substrate."},
        "surfaceFrequencyBands": _CS2_SUBSTRATE_BANDS,
        "roughness": {"base": 0.34, "variation": 0.08, "map": "independent-procedural-field"},
        "metalness": {"base": 1.0, "variation": 0.0},
        "ambientOcclusion": {"cavityStrength": 0.3, "contactShadowBias": 0.35},
        "envMapIntensity": 1.4,
        "notes": "Exposed metal revealed by wear on painted/anodized finishes.",
    }
def _cs2_hidden_material() -> dict:
    """Invisible material (opacity 0) for the organizing root group -- same trick as the
    character template's 'hidden' material, so the root component's mesh never renders."""
    return {
        "id": "hidden", "name": "Hidden (root group)", "type": "standard",
        "baseColor": "#000000", "color": "#000000",
        "colorVariation": {"palette": ["#000000", "#000000"], "pattern": "flat", "amplitude": 0.0, "heightCorrelation": 0.0},
        "albedo": {"dominant": "#000000", "secondary": ["#000000"]},
        "roughness": {"base": 1.0, "variation": 0.0},
        "opacity": {"base": 0.0},
        "notes": "Root organizing group only; not a visible surface.",
    }
def _cs2node(cid, name, primitive, position, scale, material, role, level,
             importance=0.7, local_features=None):
    """Weapon-part node. All parts parent to root with safe (non-attachment) primitives
    and names so strict-quality does not demand attachment contracts."""
    return _cnode(cid, name, primitive, "root", position, scale, material=material,
                  role=role, level=level, importance=importance,
                  local_features=local_features or [], evidence=["full-object"])
CS2_KNIFE_SUBTYPES = frozenset(
    {"karambit", "butterfly", "bayonet", "m9", "flip", "gut", "falchion", "bowie", "navaja",
     "talon", "classic"}
)
def make_cs2_component_tree(item_family: str = "knife", subtype: str | None = None) -> list:
    if item_family != "knife":
        raise ValueError(f"unsupported CS2 family {item_family!r}; only knife is implemented")
    if subtype and subtype not in CS2_KNIFE_SUBTYPES:
        raise ValueError(f"unsupported CS2 knife subtype {subtype!r}")
    # Root is an organizing group only: use the invisible 'hidden' material (opacity 0) exactly
    # like the character template, so the generator's per-component mesh for root never renders as
    # a stray box over the weapon -- no generic generator change needed.
    root = _cnode("root", "Weapon (root)", "box", None, (0, 0, 0), (1, 1, 1),
                  material="hidden", role="body", level="macro", importance=1.0, anim_role="root")
    parts = [
        _cs2node("blade", "Blade", "ground-blade", (0, 0.55, 0), (1.0, 1.0, 1.0), "skin-finish", "blade", "macro", 1.0,
                 ["edge bevel highlight", "engraved pattern swirl"]),
        _cs2node("grip", "Grip", "curve-sweep", (0, -0.55, 0), (1.0, 1.0, 1.0), "skin-finish", "grip", "macro", 0.9,
                 ["checkered grip relief"]),
        _cs2node("guard", "Guard", "extrude", (0, 0.0, 0), (1.0, 1.0, 1.0), "substrate", "guard", "meso", 0.7),
        _cs2node("pommel", "Pommel", "sphere", (0, -0.95, 0), (0.2, 0.2, 0.2), "substrate", "pommel", "meso", 0.6),
        _cs2node("bolster", "Bolster", "box", (0, 0.02, 0), (0.2, 0.18, 0.26), "substrate", "bolster", "meso", 0.6),
    ]
    return [root, *parts]
def make_cs2_feature_targets() -> list:
    return [
        {"id": "cs2-silhouette", "name": "Weapon silhouette and proportions", "tier": "critical",
         "passIds": ["blockout"], "minimumScore": 0.8, "mustPass": True,
         "componentRefs": ["root", "blade", "grip"], "evidenceRefs": ["full-object"]},
        {"id": "cs2-finish-style-read", "name": "Finish style reads correctly", "tier": "critical",
         "passIds": ["material-pass"], "minimumScore": 0.75, "mustPass": True,
         "componentRefs": ["blade"], "evidenceRefs": ["full-object"]},
        {"id": "cs2-metal-response", "name": "Metal / anodized environment response", "tier": "critical",
         "passIds": ["lighting-pass"], "minimumScore": 0.75, "mustPass": True,
         "componentRefs": ["blade", "guard"], "evidenceRefs": ["full-object"]},
        {"id": "cs2-pattern-placement", "name": "Pattern placement (approximated)", "tier": "important",
         "passIds": ["material-pass"], "minimumScore": 0.65, "mustPass": False,
         "componentRefs": ["blade"], "evidenceRefs": ["full-object"]},
        {"id": "cs2-wear-read", "name": "Wear / float reads plausibly", "tier": "important",
         "passIds": ["surface-pass"], "minimumScore": 0.65, "mustPass": False,
         "componentRefs": ["blade", "grip"], "evidenceRefs": ["full-object"]},
    ]
def apply_cs2_template(
    spec: dict,
    finish_style: str | None = None,
    *,
    skin_name: str | None = None,
    vision_finish_style: str | None = None,
    vision_confidence: float | None = None,
    float_value: float | None = None,
    paint_seed: int | None = None,
    environment_available: bool = True,
    item_family: str = "knife",
    subtype: str | None = None,
) -> dict:
    """Seed a self-consistent image-first CS2 weapon-skin spec. Object geometry reuses the
    hard-surface path (primaryDomain=object); only the finish/material recipe is CS2-specific.
    Leaves object specs untouched unless invoked. `finish_style` is treated as the explicit
    descriptor tier; resolve_cs2_finish_style() applies identity precedence against skin_name /
    vision when finish_style is not itself given."""
    resolved_style, conflicts = resolve_cs2_finish_style(
        finish_style, skin_name, vision_finish_style, vision_confidence
    )
    if resolved_style not in CS2_FINISH_PROFILES:
        raise ValueError(f"unknown finish style {resolved_style!r}; expected one of: {', '.join(CS2_FINISH_STYLES)}")
    profile = CS2_FINISH_PROFILES[resolved_style]
    spec["componentTree"] = make_cs2_component_tree(item_family, subtype)
    spec["materials"] = [_cs2_finish_material(resolved_style, float_value, paint_seed), _cs2_substrate_material(), _cs2_hidden_material()]
    spec["featureReviewTargets"] = make_cs2_feature_targets()
    # top-level signal for the pre-render environment gate (mirrors the material value)
    spec["envMapIntensity"] = profile["env"]
    spec["cs2Finish"] = {"finishStyle": resolved_style, "viewDependent": profile["viewDependent"],
                         "environment": "code-generated-default (RoomEnvironment->PMREM); user HDRI optional",
                         "environmentAvailable": environment_available,
                         "tier": "image-first"}
    # fill the assessment/contract so a normal validate passes; CS2 is held to the ultra-complex
    # bar, so strict-quality still requires the agent to enumerate the CS2 detail inventory first.
    pre = spec.setdefault("preSpecAssessment", {})
    if conflicts:
        unknowns = pre.setdefault("unknownsToResolveBeforeImplementation", [])
        unknowns.extend(conflict for conflict in conflicts if conflict not in unknowns)
    oc = pre.setdefault("objectClass", {})
    oc["primaryType"] = "weapon-skin"
    oc["primaryDomain"] = "object"
    oc["formLanguage"] = ["hard-surface", "bladed"]
    oc["structureKind"] = ["blade", "grip", "guard"]
    oc["motionPotential"] = ["static", "inspect-orbit"]
    oc["materialFamilies"] = ["metal", "anodized-coat" if profile["viewDependent"] else "painted-coat"]
    oc["domain"] = CS2_DOMAIN_ID
    complexity = pre.setdefault("complexity", {})
    complexity["tier"] = "ultra-complex"
    decision = pre.setdefault("specDepthDecision", {})
    decision["requiredDepth"] = "ultra-complex"
    decision["needsRepetitionSystems"] = True
    decision["needsMaterialLocalOverrides"] = True
    decision["minimumComponentLevels"] = ["macro", "meso", "micro"]
    inv = pre.setdefault("detailInventory", {})
    # CS2 skins are treated as ultra-complex: the finish/wear/hardware IS the item, so the detail
    # gate demands the ultra count (16). strict-quality then blocks code-gen until the agent
    # enumerates the identity-defining details -- it does not pass on the bare seed.
    inv["targetMinDetails"] = 16
    contract = spec.setdefault("qualityContract", {})
    contract["qualityBar"] = "ultra-complex"
    contract.setdefault("minimumSpecDepth", {}).update(
        {"macroComponents": 5, "mesoComponents": 16, "microFeatureGroups": 8,
         "materialLayers": 4, "repetitionSystems": 2, "reviewViewpoints": 5}
    )
    return spec
def apply_cs2_manifest_evidence(spec: dict, manifest: dict) -> dict:
    intake = {
        "schemaVersion": manifest.get("schemaVersion"),
        "state": manifest.get("state"),
        "itemFamily": manifest.get("itemFamily"),
        "subtype": manifest.get("subtype"),
        "route": manifest.get("route"),
        "exactnessTier": manifest.get("exactnessTier"),
        "identity": manifest.get("identity", {}),
        "finish": manifest.get("finish", {}),
        "paintedRegions": manifest.get("paintedRegions", []),
        "unpaintedRegions": manifest.get("unpaintedRegions", []),
        "assets": manifest.get("assets", {}),
        "camera": manifest.get("camera", {}),
        "assumptions": manifest.get("assumptions", {}),
        "confidence": manifest.get("confidence", {}),
        "provenance": manifest.get("provenance", {}),
        "warnings": manifest.get("warnings", []),
    }
    spec["cs2Intake"] = intake
    spec["exactnessTier"] = manifest.get("exactnessTier")
    if isinstance(manifest.get("camera"), dict) and manifest["camera"].get("referenceCamera"):
        spec["referenceCamera"] = manifest["camera"]["referenceCamera"]
    materials = spec.get("materials", [])
    skin = next((item for item in materials if isinstance(item, dict) and item.get("id") == "skin-finish"), None)
    if isinstance(skin, dict):
        route = manifest.get("route")
        projection = skin.setdefault("textureProjection", {})
        if route == "reference-projection":
            projection["mode"] = "projective"
            projection["source"] = manifest.get("deLitAlbedo") or manifest.get("sourceImage")
        elif route == "authored-texture":
            projection["mode"] = "uv"
            reference_pbr = manifest.get("referencePbr")
            if isinstance(reference_pbr, dict):
                skin["referencePbr"] = reference_pbr
        elif route == "procedural-finish":
            projection["mode"] = "procedural"
        skin["route"] = route
        skin["exactnessTier"] = manifest.get("exactnessTier")
        skin["paintedRegions"] = manifest.get("paintedRegions", [])
        skin["unpaintedRegions"] = manifest.get("unpaintedRegions", [])
    return spec
