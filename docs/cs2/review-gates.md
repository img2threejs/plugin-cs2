# CS2 review gates

The review contract is owned by this plugin's `tools/cs2_review.py`. It consumes a validated
manifest, render metrics, painted-region results, projection coverage, critical-feature scores,
and two orbit results. It emits a machine-readable report with family, route, exactness tier,
scene metadata, per-region confidence, approximation notes, failed gates, and a provenance block
(`mode`, `passId`, `pluginVersion`, `deferredGates`, `deferralCount`, `spuriousDeferrals`).

The versioned fixture is `tests/fixtures/knife_review_scene.json` (this plugin's copy — nothing
lives under `forge/` anymore). It records the camera, object transform, environment hash,
exposure, tone mapping, resolution, background, renderer version, visible regions, critical
features, and frozen initial thresholds:

- silhouette IoU: at least `0.85`
- aspect-ratio delta: at most `0.05`
- scale delta: at most `0.08`
- projection coverage: at least `0.85` when projection is required
- finish/material response and identity detail: at least `0.80`
- painted-region score: at least `0.80`

These thresholds are fixture data, not caller-supplied prose. There is no family or adapter gate:
every threshold is about the surface and the silhouette, and applies to any CS2 item whether or
not this plugin ships geometry for its family.

## Two modes, one tool

- **Strict (default, no flag)** — the terminal `plugin-gates` door (`gates.json`). A null metric
  fails its gate; every `deferred` entry is refused (`deferral-refused:<token>`); and
  `paintedRegions` / `criticalFeatures` must be non-empty arrays (`painted-regions-empty`,
  `critical-features-empty`).
- **Per-pass (`--allow-deferrals`)** — the checklist row (`domain.json`). The metrics file may
  defer, by explicit declaration only, the three gates whose evidence the projection bake
  produces: `finishMaterialResponse`, `identityDetail`, `projection-coverage`. The full metrics
  contract, key vocabulary, and a worked example live in
  `grimoire/intake/cs2_intake_contract.md` — a required read before authoring the manifest.

A deferred pass is a pass with named deferrals: the report lists them in `deferredGates` and the
stdout `img2.gate-verdict` envelope names each one in `reasons` (`deferred: <token>`), so the
deferral is visible in the `img2.gate-run` aggregate, not only in a file on disk.

The fixture freezes the initial targets but records calibration as pending until the browser
runtime supplies labeled positive and negative renders. `calibrate_eye.py` must be run on both
classes before these targets are treated as empirically calibrated.

Attach a report to the normal review record with (base command, run from the workspace):

```sh
python3 forge/stage4_review/append_review.py object-sculpt-spec.json \
  --pass-id material-pass --fidelity 0.9 --action continue --summary "cs2 review passed" \
  --domain-review-json cs2-review.json \
  --review-scene-json <plugin>/tests/fixtures/knife_review_scene.json --in-place
```

`append_review.py` rejects `action=continue` when the attached report is not a passing review or
when its scene fixture does not match. The report retains single-view limitations: hidden-region
confidence and approximation notes are required evidence, not an exactness claim.

The fixture metadata labels the image as `user-supplied-review-required`. Do not mark it
rights-safe or commit extracted Valve pixels until provenance is verified. Local extraction
remains outside the repository under the existing `cs2_textures/` IP boundary. Browser capture
remains the responsibility of `runtime/cs2-preview`; the Python review gate accepts its metrics
and screenshots but does not pretend to render them.
