# Capability: cs2-review-gate

## ADDED Requirements

### Requirement: Strict mode is the default

The tool SHALL honor no deferrals unless invoked with `--allow-deferrals`. In strict mode a metric
that is null or absent SHALL fail its gate exactly as before this change, and every key present in
the metrics file's `deferred` object SHALL be refused as a named failure `deferral-refused:<token>`
with verdict `reject` and exit code 1.

#### Scenario: strict invocation refuses a deferral request

- WHEN the tool runs without `--allow-deferrals` on a metrics file carrying
  `"deferred": {"finishMaterialResponse": "bake not run"}` and a null `finishMaterialResponse`
- THEN the report's `failedGates` SHALL contain `deferral-refused:finishMaterialResponse`, the
  verdict SHALL be `reject`, and the process SHALL exit 1 with a `fail` envelope.

#### Scenario: strict happy path is not stricter than today for complete metrics

- WHEN the tool runs without `--allow-deferrals` on metrics where every gate passes, with
  non-empty `paintedRegions` and `criticalFeatures` and no `deferred` key
- THEN the verdict SHALL be `pass` and the process SHALL exit 0.

### Requirement: Leniency is declared only in the per-pass command

`domain.json`'s `cs2-review` passStep command SHALL contain `--allow-deferrals`; `gates.json`'s
command SHALL NOT. A unit test reading both declaration files SHALL assert this placement.

#### Scenario: drift guard catches a lenient terminal row

- WHEN `gates.json`'s `cs2-review` command is edited to include `--allow-deferrals`
- THEN the declaration drift-guard test SHALL fail.

### Requirement: The deferrable set is closed and hardcoded

The deferrable set SHALL be exactly `finishMaterialResponse`, `identityDetail`, and
`projection-coverage`, defined as a constant in `tools/cs2_review.py` (not read from the scene
fixture or any caller-supplied input). The gates `silhouetteIoU`, `aspectRatioDelta`, `scaleDelta`,
`degenerate-orbit`, `orbit-coverage-missing`, `manifest-state`, `projection-evidence-missing`, and
all `painted-region*` / `critical-feature*` tokens SHALL never be deferrable, so a produced report
always contains at least the evaluated geometry gates.

#### Scenario: all deferrable gates deferred still evaluates geometry

- WHEN an `--allow-deferrals` run defers all three deferrable gates and the geometry and orbit
  metrics pass
- THEN the report SHALL show `failedGates: []`, `deferredGates` of length 3, and verdict `pass` —
  and a report with zero evaluated gates SHALL be impossible.

### Requirement: Deferral keys use the gate-token vocabulary and unknown keys fail

The `deferred` object's keys SHALL be gate tokens from the same vocabulary as `failedGates`
(finish: `finishMaterialResponse`; projection: `projection-coverage`, never `projection.coverage`).
A key that is not in the deferrable set — whether a non-deferrable gate token, a metric path
spelling, or a typo — SHALL produce the named failure `deferral-invalid:<key>` and verdict
`reject`; it SHALL never be silently ignored.

#### Scenario: a typo'd deferral key is a named failure

- WHEN an `--allow-deferrals` run receives `"deferred": {"finishMaterialRespone": "typo"}`
- THEN `failedGates` SHALL contain `deferral-invalid:finishMaterialRespone` and the verdict SHALL
  be `reject`.

#### Scenario: deferring a never-deferrable gate is refused

- WHEN an `--allow-deferrals` run receives `"deferred": {"silhouetteIoU": "later"}`
- THEN `failedGates` SHALL contain `deferral-invalid:silhouetteIoU` and the verdict SHALL be
  `reject`.

### Requirement: A declared deferral of an absent metric defers the gate

In `--allow-deferrals` mode the tool SHALL record a deferrable gate in `deferredGates` when its
metric is null or absent and its token is declared in `deferred`; that gate SHALL NOT appear in
`failedGates` and SHALL NOT affect the verdict. A null or absent metric without a declared
deferral SHALL fail its gate unchanged.

#### Scenario: the live-run inputs pass with declared deferrals

- WHEN the preserved metrics and manifest from workspace `test-e2e-20260902` are run with
  `--allow-deferrals` plus `"deferred"` naming `finishMaterialResponse`, `identityDetail`, and
  `projection-coverage`
- THEN the verdict SHALL be `pass` with `failedGates: []` and `deferredGates` equal to those three
  tokens.

#### Scenario: prose-only deferral grants nothing

- WHEN the same live-run metrics are run with `--allow-deferrals` but no `deferred` key (prose
  fields `projection.state` and `measurementProvenance.nulls` present, as authored)
- THEN the verdict SHALL be `reject` with the same three gates in `failedGates`.

### Requirement: A deferral conflicting with a present metric is a named hard failure

In `--allow-deferrals` mode, a declared deferral whose metric is present and failing SHALL fail
the gate and add `deferral-conflict:<token>`; a declared deferral whose metric is present and
passing SHALL be evaluated normally and recorded under `spuriousDeferrals`, not `deferredGates`.

#### Scenario: deferred but present-and-failing

- WHEN `finishMaterialResponse` is 0.1 (below threshold) and also declared in `deferred`
- THEN `failedGates` SHALL contain both `finishMaterialResponse` and
  `deferral-conflict:finishMaterialResponse`, and the verdict SHALL be `reject`.

#### Scenario: deferred but present-and-passing

- WHEN `identityDetail` is 0.95 and also declared in `deferred`
- THEN the gate SHALL be evaluated normally, `deferredGates` SHALL NOT contain `identityDetail`,
  and `spuriousDeferrals` SHALL contain it.

### Requirement: Deferring projection coverage requires the projection block

Deferring `projection-coverage` SHALL require `projection.required: true` to be present in the
metrics; a metrics file with the `projection` block absent SHALL keep producing the non-deferrable
`projection-evidence-missing` failure regardless of any deferral declaration.

#### Scenario: omitted projection block is not deferrable

- WHEN an `--allow-deferrals` run declares `"deferred": {"projection-coverage": "bake later"}` but
  the metrics contain no `projection` object
- THEN `failedGates` SHALL contain `projection-evidence-missing` and the verdict SHALL be
  `reject`.

### Requirement: Strict mode rejects empty evidence arrays

In strict mode, `paintedRegions` and `criticalFeatures` SHALL each be non-empty arrays; an empty
or absent array SHALL produce the named failure `painted-regions-empty` or
`critical-features-empty` respectively, unconditionally for every family. In `--allow-deferrals`
mode empty arrays SHALL retain their previous behavior.

#### Scenario: empty painted regions fail the strict door

- WHEN the tool runs without `--allow-deferrals` on metrics carrying `"paintedRegions": []`
- THEN `failedGates` SHALL contain `painted-regions-empty` and the verdict SHALL be `reject`.

### Requirement: The envelope names deferrals with machine-generated reasons

On a passing run with one or more deferrals, the `img2.gate-verdict` envelope SHALL carry
`status: "pass"` with non-empty `reasons` consisting solely of machine-generated strings of the
form `deferred: <token>`, and `evidence` SHALL include `deferredGates` and `mode`. Agent-authored
reason text SHALL NOT appear in the envelope.

#### Scenario: deferred pass is visible in the aggregate

- WHEN an `--allow-deferrals` run defers `finishMaterialResponse` and passes
- THEN stdout SHALL contain exactly one parseable `img2.gate-verdict` with `status: "pass"`,
  `reasons` containing `deferred: finishMaterialResponse`, and `evidence.deferredGates` naming it.

### Requirement: The deferred map is shape-validated with hard limits

`deferred` SHALL be a JSON object whose values are plain strings of at most 200 characters. A
non-object `deferred`, a non-string value, or an over-length value SHALL be a structural error:
exit code 2 with an `error` envelope naming the cause. Over-length reasons SHALL never be
truncated.

#### Scenario: non-object deferred is a structural error

- WHEN the metrics carry `"deferred": ["finishMaterialResponse"]`
- THEN the tool SHALL exit 2 and stdout SHALL carry an `error` envelope whose reasons name the
  malformed `deferred` shape.

### Requirement: Every report is self-describing

Every report SHALL always contain: `deferredGates` (an array, empty when no deferrals — never
omitted), `deferralCount` (integer), `spuriousDeferrals` (array), `mode` (`"strict"` or
`"allow-deferrals"`), `passId` (echoed once from the metrics file's top-level `passId`, null when
absent), and `pluginVersion` (read from the plugin's own `plugin.json`).

#### Scenario: a clean strict report still carries the provenance block

- WHEN a strict run passes with no deferral declarations
- THEN the report SHALL contain `deferredGates: []`, `deferralCount: 0`, `mode: "strict"`, and a
  non-empty `pluginVersion`.

### Requirement: Unrecognized CLI arguments produce an error envelope

An unrecognized command-line argument SHALL cause the tool to print one `img2.gate-verdict`
envelope with `status: "error"` naming the offending argument on stdout before exiting 2, instead
of argparse's bare usage text on stderr alone.

#### Scenario: stale-install flag mismatch is diagnosable

- WHEN the tool is invoked with a flag it does not recognize
- THEN stdout SHALL contain exactly one parseable `error` envelope whose reasons include the
  unrecognized argument, and the exit code SHALL be 2.

### Requirement: The producer contract documents the metrics-file schema

`grimoire/intake/cs2_intake_contract.md` (the mandatory-read intake step) SHALL document the
metrics file's schema including the `deferred` object, its gate-token vocabulary, the closed
deferrable set, the reason-string limits, and a worked example; `docs/cs2/review-gates.md` SHALL
be corrected to describe the plugin-resident tool and current gates (no `forge/…` paths, no
removed family/adapter gate) and the same deferral contract.

#### Scenario: the intake contract teaches the deferral key

- WHEN an agent completes the `cs2-contract-read` step
- THEN the document it read SHALL contain the `deferred` schema and a worked example naming the
  three deferrable tokens.
