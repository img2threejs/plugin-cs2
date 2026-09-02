# Proposal: phase-aware-cs2-review

## Why

The first full-pipeline run of a non-knife item (MP9 "Wild Lily", live e2e workspace
`test-e2e-20260902`, 2026-09-02) exposed a structural defect in the `cs2-review` gate: in every
pass before `material-pass` it rejects on metrics that **cannot exist yet**
(`finishMaterialResponse: null`, `identityDetail: null`, `projection.coverage: null` — the metrics
file itself records `projection.state: "bake not yet run; projection lands in material-pass"`),
while every metric that can exist passed (`silhouetteIoU 0.8629` against the 0.85 floor,
`aspectRatioDelta 0.0099`, `scaleDelta 0.0008`).

The observed consequence: the driving agent **bypassed the gate's enforcing consumer** — it never
attached the report via `append_review.py --domain-review-json` (all three `reviewHistory` entries
carry no `domainReview`/`cs2Review` key), documenting its reasoning in `visualEvidence.notes`
("DOMAIN GATE DEFERRED, NOT WAIVED … a gate-ordering conflict between the base's locked-sequential
passes and the plugin's single unscoped finish gate"). The attachment is optional in the base
(`append_review.py` declares `--domain-review-json` without `required=True`), so the block at
`append_review.py:373` never ran. A blocking gate that fires on structurally-unsatisfiable
conditions trains its consumers to route around it, which erodes its authority exactly where it is
legitimate (post-bake).

This proposal removes the unsatisfiable-condition provocation. It does **not** close the
non-attachment bypass (base-side; tracked separately — see Non-scope) and therefore does not claim
to restore per-pass enforcement authority on its own.

The defect is pre-existing behavior carried over from the base's `CS2_PASS_STEPS`; it is newly
*visible* because plugin extraction (img2threejs PR #106, branch `lab/cs2-plugin`) made non-knife
full-pipeline runs reachable. The base `main` branch (v1.5.1) still carries its own copy of the
same logic; that copy is superseded by the extraction, not fixed here.

## What Changes

1. **Strict is the default; leniency is the explicit opt-in.** By default `cs2_review.py` honors
   no deferrals: a metric that is null or absent fails, exactly as today, and any `deferred`
   request in the metrics file is itself refused as a named failure. The per-pass command in
   `domain.json` gains `--allow-deferrals`; `gates.json` stays flagless and therefore strict. A
   copy-pasted row, a dropped flag, or a hand-edited `gates.json` fails **closed** (noisy per-pass
   behavior), never open (lenient final door).
2. **Deferral is explicit, keyed by gate token.** In `--allow-deferrals` mode only, a metric may be
   deferred via a top-level `"deferred": {"<gate-token>": "<reason>"}` object in the metrics file.
   The key vocabulary is the same one `failedGates` uses. The deferrable set is closed, hardcoded
   in the tool, and exactly: `finishMaterialResponse`, `identityDetail`, `projection-coverage` —
   the metrics produced by the projection bake. Geometry and orbit gates are never deferrable, so a
   report with zero evaluated gates is impossible by construction. `painted-region` checks are NOT
   deferrable: they are vacuous when the array is empty (a pre-existing hole this change closes at
   the strict door instead — see 4).
3. **Deferral semantics are total.** deferred + null ⇒ recorded in `deferredGates`; deferred +
   present-and-failing ⇒ hard failure plus `deferral-conflict:<token>`; deferred +
   present-and-passing ⇒ evaluated normally, recorded as spurious; not-deferred + null ⇒ failure
   (the existing anti-laziness property, unchanged). An unknown or non-deferrable key in
   `deferred` is a named failure (`deferral-invalid:<key>`), never a silent no-op. Deferring
   `projection-coverage` requires `projection.required: true` to still be present; an omitted
   `projection` block keeps hitting the non-deferrable `projection-evidence-missing`.
4. **The strict door gets real teeth for the vacuous arrays.** In strict mode, `paintedRegions`
   and `criticalFeatures` must be non-empty arrays; empty or absent is a named failure
   (`painted-regions-empty`, `critical-features-empty`), unconditionally — a CS2 skin is a paint
   job, there is no family for which paint is not implied. Today an agent shipping
   `"paintedRegions": []` passes those gates outright at every door; that falsified "nothing is
   loosened at the final door" before this change existed.
5. **The report becomes self-describing.** Every report always carries: `deferredGates` (empty
   array when none — never omitted), `deferralCount` (scalar a base consumer can key on later),
   `spuriousDeferrals`, `mode` (`"strict"` | `"allow-deferrals"`), top-level `passId` echoed from
   the metrics file, and `pluginVersion` read from `plugin.json`. This is one deliberate
   byte-level report change; the byte-frozen oracle fixture is re-recorded in the same commit, as
   its own failure message mandates.
6. **The envelope names deferrals.** On a deferred pass the `img2.gate-verdict` envelope carries
   machine-generated non-empty `reasons` (`"deferred: <token>"`) and `evidence.deferredGates` +
   `evidence.mode` — verified compatible with `gate_runner.parse_verdict` (reasons on a `pass`
   envelope pass through untouched). Agent-authored reason prose stays confined to the report
   file: values must be plain strings ≤ 200 characters, and a violation is a hard error (exit 2),
   never a truncation.
7. **Unrecognized CLI arguments produce an `error` envelope on stdout before exit 2** instead of
   argparse's bare stderr usage text — the misclassification wart that made v0.1.0's gate failures
   opaque, one layer down.
8. **The contract documentation is the load-bearing deliverable.** Nothing today teaches the
   driving agent that `deferred` exists — the live agent expressed deferral as prose in exactly
   the fields that grant nothing. The metrics-file schema (including `deferred`, its vocabulary,
   and a worked example) is documented in `grimoire/intake/cs2_intake_contract.md` (a
   mandatory-read step) and in `docs/cs2/review-gates.md`, which is also corrected: it currently
   describes the pre-extraction `forge/…` paths and a family/adapter gate that v0.1.0 removed.

## Breaking changes

- The report gains fields (`deferredGates`, `deferralCount`, `spuriousDeferrals`, `mode`,
  `passId`, `pluginVersion`); the byte-equality oracle fixture is re-recorded in the same commit
  (`tests/test_cs2_oracle_replay.py`'s own mandate). `tests/test_cs2_review.py`'s five cases
  survive unchanged (none enumerates the key set); the oracle replay does not — "existing cases
  keep passing" is true per-module, not suite-wide.
- A per-pass (`--allow-deferrals`) run that previously exited 1 on unproducible metrics may now
  exit 0 with named deferrals. Honest limitation, stated plainly: the base's
  `append_review.py:373` keys on `verdict` alone, so a deferred pass is accepted by it exactly as
  a clean pass until the base learns to key on `deferralCount` (base-side, Non-scope), and the
  non-attachment escape used in the live run remains open regardless.
- The `img2.gate-verdict` envelope shape is unchanged (§9); deferral detail rides in `reasons` +
  `evidence`.

## Capabilities

- **Modified capability: `cs2-review-gate`** — the blocking review gate contract: modes, deferral
  rules, vocabulary, verdict computation, report and envelope shape, and the documentation
  contract that teaches producers the metrics-file schema.

## Affected code and systems

- `tools/cs2_review.py` — mode flag, deferral validation/semantics, non-emptiness checks, report
  fields, envelope reasons, error-envelope-on-bad-args; `_failed_threshold` call sites split so
  "missing" and "failing" are distinguishable.
- `domain.json` — per-pass command gains `--allow-deferrals`.
- `gates.json` — unchanged (strict by default); a drift-guard unit test asserts the flag placement
  across both files.
- `grimoire/intake/cs2_intake_contract.md`, `docs/cs2/review-gates.md` — metrics-file schema and
  corrected gate documentation.
- `tests/` — new deferral/strict/envelope/CLI cases (enumerated in tasks), oracle fixture
  re-recorded plus a strict-mode oracle companion, `COLLECTED_FLOOR` raised in
  `test_suite_integrity.py`.
- `CHANGELOG.md`, `plugin.json` — release v0.1.2.
- Consumers, stated precisely: `img2 harness gate_runner` / base `run_gates.py` read the envelope
  (no changes; deferrals become visible in `reasons`/`evidence`); the base's
  `forge/stage4_review/append_review.py` is an automated consumer of the report that keys on
  `verdict` alone and stores the whole report into `reviewHistory` — additive fields are safe
  there, and the deferred-pass-reads-as-clean-pass consequence is recorded under Breaking changes.

## Scope

Everything under "What changes", the test matrix in `tasks.md`, the documentation updates, the
oracle re-record, CHANGELOG, release v0.1.2, and reinstall (`img2 add img2threejs/plugin-cs2 --ref
v0.1.2 --force` — gates execute from `$IMG2_HOME/plugins/cs2`, never the checkout, so an
un-reinstalled 0.1.1 silently keeps today's behavior; the `pluginVersion` stamp makes that state
detectable in any report).

## Non-scope (each tracked, none silently dropped)

- **Making `--domain-review-json` mandatory when a workspace resolves a domain profile** — the
  real fix for the observed bypass; base-side (img2threejs). Until it lands, the per-pass row's
  authority is advisory: the "keep the per-pass row" justification in design.md is written
  conditionally on that change, not in the present tense.
- **Base `append_review.py` keying on `deferralCount`** — base-side; residual risk stated under
  Breaking changes.
- **`IMG2_GATE_PHASE` injected by the harness gate runner** — the only tamper-proof "is this the
  terminal invocation" seam (one line at `gate_runner.py`'s env construction); recorded as the
  durable third layer on top of strict-default + drift-guard, tracked as a harness issue. Shipping
  it alone would reintroduce fail-open for agent-run invocations, so it complements rather than
  replaces this change.
- Per-family review scenes and threshold recalibration (the scene's `calibration.status` is
  frozen-awaiting-corpus with empty fixture lists; pre-terminal verdicts therefore rest on three
  knife-calibrated geometry thresholds — acknowledged, not fixed here).
- `maxOrbitCollapseRatio` is declared in the scene and `REQUIRED_THRESHOLDS` but never applied
  (the orbit gate is two agent-written booleans today) — pre-existing, tracked.
- The `tools/cs2_review_contract.py` / scene-fixture two-contract split and the README instruction
  pointing at the dead one (`GOLDEN_THRESHOLDS`) — pre-existing; the canonical vocabulary for this
  change is the fixture's `thresholds` plus the report's gate tokens.
- The base `main`-branch copy of `cs2_review.py` / `CS2_PASS_STEPS` (superseded by the extraction).
- The base state-machine drift observed in the same live run (separate base issue).

## Acceptance criteria

Preconditions: base = img2threejs branch `lab/cs2-plugin` at `5ca9f81` or later (the `main` copy
still ships the defect and would produce a false "fix does not fix it"); installed plugin =
v0.1.2 (`~/.img2/plugins/cs2`).

1. **Per-pass artifact:** a real pre-material `cs2-review.json` showing `verdict: "pass"`,
   `failedGates: []`, `deferredGates: ["finishMaterialResponse", "identityDetail",
   "projection-coverage"]`, `mode: "allow-deferrals"` — the direct counterpart of the live run's
   reject.
2. **Attachment evidence:** for that same pass, a `reviewHistory` entry with
   `domainReview`/`cs2Review` populated (report attached via `--domain-review-json`) and no
   hand-written override justification in `visualEvidence.notes`. Not enforceable by this change
   alone (depends on the contract docs steering the agent); captured as delivery evidence.
3. **A captured strict execution via the harness path:** an `img2.gate-run` aggregate from
   `run_gates.py` at `plugin-gates`, on a workspace whose metrics carry a `deferred` block,
   showing `cs2-review` `status: "fail"` with the deferral named in `reasons` and `stopped: true`
   — the first real execution this path will ever have had.
4. **Green suite, floor raised:** full plugin suite passing with `COLLECTED_FLOOR` raised to the
   new count, and the oracle fixture diff showing only the intended new fields.

## Open questions

None. The three raised during review are decided and recorded in design.md: deferral audit uses a
single top-level `passId` (not per-entry `until`); the artifact-of-record ambiguity is answered by
the `mode` stamp; the deferrable set stays hardcoded in the tool (Reviewer B's fixture-as-data
position and the recorded revisit trigger — per-family scenes exist AND scene selection is no
longer a free CLI argument — are in design.md).
