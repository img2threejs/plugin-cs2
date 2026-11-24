# CS2 review gates

The review contract is owned by this plugin's `tools/cs2_review.py`. It consumes a validated
manifest, render metrics, painted-region results, projection coverage, critical-feature scores,
and two orbit results. It emits a machine-readable report with family, route, exactness tier,
scene metadata, per-region confidence, approximation notes, failed gates, and a provenance block
(`mode`, `passId`, `pluginVersion`, `deferredGates`, `deferralCount`, `spuriousDeferrals`).

The production terminal gate replays `.img2/cs2-terminal/inputs.json` and checks
`.img2/cs2-terminal/scene.json` against the actual pinned capture configs. The
golden `tests/fixtures/knife_review_scene.json` remains a test oracle, never the
production camera. Frozen terminal thresholds live in `TERMINAL_THRESHOLDS`:

- silhouette IoU: at least `0.85`
- aspect-ratio delta: at most `0.05`
- scale delta: at most `0.08`
- projection coverage: at least `0.85` when projection is required
- finish/material response and identity detail: at least `0.80`
- painted-region score: at least `0.80`

These thresholds are program-owned policy, not caller-supplied prose. There is no family or adapter gate:
every threshold is about the surface and the silhouette, and applies to any CS2 item whether or
not this plugin ships geometry for its family.

Scene thresholds must equal `TERMINAL_THRESHOLDS` exactly, including keys and numeric
types (booleans are refused); non-finite values are refused. This applies to both
scene-file loading and direct evaluator calls, including decision-adapter recomputation.
Deferral semantics do not change: only genuinely missing approved metrics can defer,
never geometry failures or present failing metrics.

Before each per-pass evaluation, `domain.json` invokes:

```sh
python3 PLUGIN/tools/cs2_review.py --prepare-scene \
  --manifest cs2-intake.json --out cs2-review-scene.json
```

This validates the admitted manifest and its legacy `reviewScene` policy, then copies
its current camera/transform/environment into the evaluator schema with frozen review
thresholds. It does not reuse a previous run's scene or the historical fixture. The
result is per-pass policy, not authenticated capture evidence or terminal approval.


## Two modes, one tool

- **Terminal (`--terminal-inputs`)** — the `plugin-gates` door (`gates.json`).
  Recomputes all metrics and current scene from pinned workspace evidence; authored
  metrics and deferrals are refused. The envelope binds the current base artifact.
  Replay proves integrity only: the base must authenticate capture production,
  source/classifier provenance and same-artifact semantic quality review.
- **Strict metric evaluation (default)** — the local evaluator also refuses null
  metrics, any deferral, and empty painted-region/critical-feature lists.
- **Per-pass (`--allow-deferrals`)** — the checklist row (`domain.json`). The metrics file may
  defer, by explicit declaration only, the three gates whose evidence the projection bake
  produces: `finishMaterialResponse`, `identityDetail`, `projection-coverage`. The full metrics
  contract, key vocabulary, and a worked example live in
  `grimoire/intake/cs2_intake_contract.md` — a required read before authoring the manifest.

A deferred pass is a pass with named deferrals: the report lists them in `deferredGates` and the
stdout `img2.gate-verdict` envelope names each one in `reasons` (`deferred: <token>`), so the
deferral is visible in the `img2.gate-run` aggregate, not only in a file on disk.

Threshold calibration is not claimed. Synthetic tests and matching digests are
neither an independent expert corpus nor authenticated evidence. Real source
observations and independently approved annotations are required by the terminal
producer; see README's production terminal handoff contract.

The fixed terminal gate argv remains pinned by core. Non-routed trusted-host evidence
production and routed run-specific gate paths need a coordinated core change; this
plugin does not bypass missing terminal inputs with per-pass authored metrics.


Attach a report to the normal review record with (base command, run from the workspace):

```sh
python3 forge/stage4_review/append_review.py object-sculpt-spec.json \
  --pass-id material-pass --fidelity 0.9 --action continue --summary "cs2 review passed" \
  --domain-review-json cs2-review.json \
  --review-scene-json .img2/cs2-terminal/scene.json --in-place
```

`append_review.py` rejects `action=continue` when the attached report is not a passing review or
when its scene fixture does not match. The report retains single-view limitations: hidden-region
confidence and approximation notes are required evidence, not an exactness claim.

Do not mark source pixels rights-safe or commit extracted Valve pixels until
provenance is verified. Local extraction remains outside the repository under the
existing `cs2_textures/` IP boundary. Production capture is delegated through the
explicit trusted host to the base's fixed delivered-GLB renderer; the plugin never
authenticates capture from a caller-hashed renderer report.
