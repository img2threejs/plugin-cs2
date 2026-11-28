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
attach the classification record, resolve the family, and choose `route` independently
from `exactnessTier`. Missing classification, confidence below 0.82, a timeout, or a negative
CS2 classification is `request-input`, even for a selected route. A family without authored geometry
retains the finish contract and records `geometrySource: agent-inferred`.

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
2. Record the heuristic CS2 signal as triage only. `detect_cs2.py` is never an input to route
   selection or authoritative identity evidence.
3. Require an independent classification record before selecting a family adapter. If classification
   is absent, timed out, below 0.82, or negative for CS2, return `request-input`.
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

## Recorded profile selection and trust boundary

`--profile cs2` remains explicit legacy selection. A base-validated `img2.route-decision` v1 may
also select `profile:cs2@<resolvedSha>` for one object. The base must first verify its own journal,
lease, eligibility, current image/inventory/box/context bindings and selected provider resolution.
This plugin does not import the base controller or authenticate the journal.

The manifest API accepts `route_decision`, `validated_route_sha256`, `object_id`, and `resolved_sha`.
The equivalent CLI flags are `--route-decision`, `--validated-route-sha256`, `--object-id`,
and `--resolved-sha`. The digest uses canonical JSON (sorted keys, compact separators, UTF-8,
no non-finite numbers). **The supplied digest is only an integrity comparison, not authentication**:
an untrusted caller can forge both a document and its digest. These flags are a trusted base-caller
interface, not a standalone authorization service. The plugin verifies the completed decision,
object selection/eligibility, exact provider pin and reference SHA256 against that handoff.
The reference is the image bound by the decision; a cropped child requires the base to hand off
its independently validated image binding rather than substituting a crop silently.

The handoff is retained under `extensions.routeSelection`; it never enters `identity` or
`classification`. Even a matching forged route hash cannot replace classification. Existing
classification records remain accepted; explicit `isCs2: false`, a non-`cs2` `domain`, or
`kind: non-cs2|look-alike|unknown` vetoes identity. Explicit user metadata cannot bypass this veto.
Routed `--resume` rechecks classification and the current handoff instead of trusting a cached
`proceed`. Routed augmentation and strict review also reject a forged `proceed` lacking classification.

## Offline four-group decision inputs

`tools/cs2_decision_adapter.py` exposes local snapshots; the base alone performs Jev-first
consultation, consent, shared budgeting, decision persistence and trial application:

```bash
python3 /path/to/plugin-cs2/tools/cs2_decision_adapter.py \
  --workspace /path/to/child --group quality-review \
  --evidence evidence-bindings.json --pass-id material-pass --out cs2-decision-snapshot.json
```

`--evidence` is a JSON list of shared-controller bindings `{role, path, sha256}`. Paths are
workspace-relative, regular files, without symlinks or traversal; hashes are supplied from the
current revision and verified before and after evaluation. Never derive a success claim from the
existence of these files. `manifest` and `reference` are always required; the manifest reference
must carry a matching real-byte `sourceViews[].sha256` (old manifests need regeneration).
Quality-review/repair additionally require `spec`, `source`, `metrics`, `review-scene`, `gate`,
`camera`, `render`, `view-front`, `view-orbit-a`, and `view-orbit-b`. The base must produce and bind
the actual matched camera/renders and measurements; this adapter does not render, measure pixels,
prove camera alignment, or invent missing evidence. It recomputes the strict CS2 report and refuses
a report inconsistent with the current manifest/metrics/scene or pass. A failed gate stays failed.

Snapshots expose the controller's `bindings`, `candidates`, `observations`, and `requirements`;
the full `gate` report remains local, not provider projection. The base independently validates
bindings and strips their paths before provider projection. Routing snapshots do not enumerate or
resolve providers: the base owns that.
Strategy and repair accept `plan_input` (CLI: `--plan-input`) only from trusted base code.
Its exact shape is `{plans, scope, proposalRoles}`. Every plan uses the shared shape
`{id, passId, components, operations, fieldPaths, materialSources, dependencies, rigHandoff}`.
`scope` contains the shared `filter_plans` keyword fields: `pass_id`, `pass_unlocked`,
`components`, `operations`, `field_paths`, `authorized_sources`, `available_dependencies`,
`rig_required`, and `rig_available`. JSON allowlists are arrays; the API also accepts sets.
For repair, scope additionally requires `permissions`; mutation requires explicit `write-spec`.
These values must come from independently checked program-owned scope, never from a provider,
candidate, manifest or its filename. Supplying JSON does not authenticate authorization.

`proposalRoles` maps plan ids to evidence binding roles containing complete successor spec bytes.
Every successor is hash-checked with the other inputs. Proposed changes must be non-empty,
limited to existing named components and exact component-relative `fieldPaths`; component
membership/order, global spec fields, quality floors, gates and provenance remain frozen.
Material edits require real bound SHA256s in `materialSources` that are independently present
in `scope.authorized_sources`; neither source paths nor invented licensing labels grant permission.
Operations and dependencies must already be supported by the trusted scope. The base still runs
its authoritative `filter_plans`, `StrategyDecision` and full spec/provenance validators.
Strategy with plan input also requires current `spec`, `source`, and `critical-features` bindings.

No default template application, global route/material/camera mutation, no-op, or guessed plan is
emitted. Missing concrete admissible proposals yields an empty candidate list, not an executable
fallback. CS2 global `materials`, `cs2Intake.route`, and `referenceCamera` changes cannot be
expressed under the current component-only strategy application contract and remain blocked.
`--unlocked` is trusted base-caller input, not authorization by itself.

Repair requires a fresh strict failure and wraps only an eligible concrete plan as
`{id, hypothesis, action, plan, permissions}`, with the same plan id and `action: refine-spec`.
It does not synthesize `request-input` as a fake executable plan. The base chooses request-input
when no candidate is admissible and still verifies the complete failure envelope, actual
permissions, revision, locks, shared deadline/counters and post-trial gates. Snapshots and
candidates never authorize canonical continuation or establish successful repair.
