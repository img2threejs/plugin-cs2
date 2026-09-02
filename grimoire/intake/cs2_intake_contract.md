# CS2 Intake Contract

Read this reference completely for every CS2 request before creating `cs2-intake.json` or running
pre-spec assessment. Do not advance the local checklist until its classification and manifest
requirements are satisfied.

For a CS2 item, the target is observable agreement between the supplied image and the rendered
item: silhouette, proportions, edge profile, hardware layout, coating colour, pattern placement,
wear, roughness response, and camera framing. Every decision must be traceable to evidence or be
labelled as an approximation.

This plugin serves **any** CS2 item. The finish system -- paint seed, float, wear, finish style --
is identical across families and is the part of this domain the base pipeline cannot infer, so a
rifle, a glove and a knife all get it. Only the component *tree* is family-specific: where this
plugin has authored geometry it supplies it and records `componentAdapter`; where it does not, the
manifest records `geometrySource: agent-inferred`, the augmentation omits `componentTree`, and the
run authors the shape from the reference. Never a stopped run, and never another family's tree as
a fallback.

## When to build `cs2-intake.json`

For a CS2 request, create and validate `cs2-intake.json` before pre-spec authoring. Run admission
and probing for every source view, record the heuristic signal as non-authoritative evidence,
attach the classification record, resolve the supported family, and choose `route` independently
from `exactnessTier`. Missing classification, insufficient coverage, or a contradictory
high-confidence class is `request-input`; unsupported families do not continue into spec
generation.

## Layer contract

Pass these records between layers. Do not copy an informal vision description into the next stage:

| Layer | Owns | Must emit | Must not decide alone |
| --- | --- | --- | --- |
| Intake | view validity and technical evidence | role, path/hash, resolution, coverage, duplicate status, admission verdict | item identity from aspect ratio or filename |
| Classification | semantic identity | family, subtype, confidence, evidence refs, provider/version, timeout state | geometry or finish parameters |
| Identity | skin/name/paint metadata | precedence, resolved values, ambiguity candidates, provenance | guessed paint index, float, or seed |
| Surface evidence | pixels and texture sources | de-lit reference, PBR channels, map provenance, colour space, UV orientation, confidence | albedo reused as roughness/normal/AO |
| Geometry adapter | family-specific form | component tree, topology, dimensions, edge/spine, hardware relationships, painted regions | hidden geometry without confidence notes |
| Spec/route | evidence-backed implementation choice | route, exactness tier, assumptions, feature targets, camera contract | exact-texture claim without exact evidence |
| Build/review | rendered observables | fixed view, two non-degenerate orbit views, per-region results, failed gates, next action | overriding a failed critical feature with a global score |

The canonical hand-off is `cs2-intake.json` (`schemaVersion: 1`). Its state is one of
`proceed`, `request-input`, `fallback`, `rejected`. Write it atomically and preserve unknown provider fields under
`extensions`; a fallback must never erase prior evidence.

## CS2 intake order

1. Admit and technically probe every view. Reject undecodable, empty, tiny, fragmented, or
   duplicate references before classification.
2. Record the heuristic CS2 signal only as a routing hint. `detect_cs2.py` is never authoritative
   identity evidence.
3. Require a classification record before selecting a family adapter. If classification is absent,
   timed out, or contradicts a high-confidence objectness result, return `request-input`.
4. Resolve identity in this order: explicit user metadata, uniquely resolved metadata, then the
   authoritative classification record. Preserve ambiguity rather than guessing.
5. Select route and exactness independently:
   - `reference-projection`: default for matching a specific patterned image;
   - `authored-texture`: only when independent texture maps are supplied or legally acquired;
   - `procedural-finish`: fallback when projection evidence is unavailable or live response is the
     stated priority.
   Exactness is `image-only`, `metadata-assisted`, or `exact-texture`; changing route must not
   silently upgrade or downgrade the evidence tier.
6. Select the knife adapter only after family/subtype validation. Record painted regions, unpainted
   substrate, visible hardware, hidden-region confidence, and every approximation in the spec.
7. For projection, solve the camera and de-light the source first. Projected pixels provide colour
   evidence, not automatic geometry truth; geometry still comes from the adapter and silhouette
   review.

## Surface and review rule

For a specific CS2 reference, preserve the reference's own colour/pattern pixels whenever legal and
technically possible. Procedural Doppler/Fade/Gamma/Marble patterns are not equivalent to the input
image and may only be used with an explicit `procedural-finish` route and approximation warning.
Keep albedo, roughness, metalness, normal/height, AO, mask, and wear as independent channels. Record
channel source, colour space, UV orientation, dimensions, packed-channel decoding, and missing-channel
derivation. A low-confidence PBR inference is a refine-input signal, not proof of exact material.

Single-view reconstruction may proceed only when visible identity features are sufficiently covered;
hidden blade sides, underside, and back hardware must carry inference confidence and may trigger
`request-input`. Review the fixed camera plus two meaningful orbit views. Report what changed, which
evidence caused it, what still differs, and choose exactly one next action:
`continue`, `refine-spec`, `refine-code`, `request-input`, or `stop`.

## Review metrics file contract (`cs2-review-inputs.json`)

The per-pass review step and the terminal gate both run
`tools/cs2_review.py --metrics cs2-review-inputs.json`. You author that file each pass. Beyond the
measured metrics (`silhouetteIoU`, `aspectRatioDelta`, `scaleDelta`, `finishMaterialResponse`,
`identityDetail`, `paintedRegions`, `criticalFeatures`, `projection`, `multiAngle`, `passId`), it
carries ONE mechanism for a metric that cannot exist yet:

- **`deferred`** — an object mapping a gate token to a short reason string (≤ 200 characters,
  plain string, never truncated). Prose anywhere else (`projection.state`, provenance notes)
  grants NOTHING: a null metric without a `deferred` entry fails its gate.
- The deferrable set is closed and fixed: `finishMaterialResponse`, `identityDetail`,
  `projection-coverage` — the metrics the projection bake produces, which do not exist before
  material-pass. Keys are gate tokens (the `failedGates` vocabulary): projection is
  `projection-coverage`, never `projection.coverage`. Any other key — geometry gates, painted
  regions, typos — is refused as `deferral-invalid:<key>`.
- Deferral is honored only by the per-pass invocation (`--allow-deferrals`, already present in
  this plugin's `domain.json` row). The terminal `plugin-gates` door runs strict: every `deferred`
  entry there is refused (`deferral-refused:<token>`), a null metric fails, and `paintedRegions`
  and `criticalFeatures` must be non-empty.
- Deferring `projection-coverage` still requires `"projection": {"required": true, "coverage": null}`
  to be present. A deferred metric that turns out to be present-and-failing is a contradiction
  (`deferral-conflict:<token>`) and rejects.

Worked example for a pre-material pass (blockout through form-refinement):

```json
{
  "passId": "form-refinement",
  "silhouetteIoU": 0.86,
  "aspectRatioDelta": 0.01,
  "scaleDelta": 0.001,
  "finishMaterialResponse": null,
  "identityDetail": null,
  "paintedRegions": [],
  "criticalFeatures": [{"id": "receiver-silhouette", "score": 0.82}],
  "projection": {"required": true, "coverage": null},
  "multiAngle": {"degenerate": false, "angles": [{"id": "front", "azimuth": 0}, {"id": "right", "azimuth": 90}]},
  "deferred": {
    "finishMaterialResponse": "bake not yet run; lands in material-pass",
    "identityDetail": "bake not yet run; lands in material-pass",
    "projection-coverage": "bake not yet run; lands in material-pass"
  }
}
```

The report the gate writes back records `mode`, `passId`, `pluginVersion`, `deferredGates`,
`deferralCount`, and `spuriousDeferrals`, so a later reader can tell which rules judged which
pass. Attach the report to the review record via `append_review.py --domain-review-json`; a
deferred pass is a pass with named deferrals, not a waiver.
