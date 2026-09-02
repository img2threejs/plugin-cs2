# Design: phase-aware-cs2-review

## Context

`tools/cs2_review.py` serves two invocations with one byte-identical command today: the per-pass
checklist row (`domain.json` passSteps, spliced before `ai-review-recorded` in every correction
pass) and the terminal blocking gate (`gates.json`, executed by the harness gate runner at
`plugin-gates`, which `run_gates.py` reaches only after `assert_action_ready` and after
`emission-target` in FINAL_STEPS order). The tool fails any threshold whose metric is not a number
(`_failed_threshold`), which is a deliberate anti-laziness property — and a structural false
positive in passes that precede the projection bake, whose outputs (`finishMaterialResponse`,
`identityDetail`, `projection.coverage`) only exist from `material-pass` on.

Live evidence (workspace `test-e2e-20260902`): geometry gates passed on an MP9 against
knife-calibrated thresholds; the three bake-dependent metrics were null with prose explanations;
the gate rejected every pre-material pass; the driving agent routed around the enforcing consumer
by not attaching the report (`--domain-review-json` is optional in the base), documenting why.

## Goals

- Per-pass invocations stop failing on structurally-unsatisfiable conditions, without granting the
  metrics author (the driving agent) any implicit leniency.
- The strict door loses no strength and gains teeth where it was already vacuous
  (empty `paintedRegions`/`criticalFeatures`).
- Every report and envelope self-describes which rules it was judged under.
- The producer contract is documented where the agent is already required to read.

## Non-goals

See proposal Non-scope. In particular: no base or harness changes, no threshold recalibration, no
per-family scenes.

## Decisions

### D1 — Strict by default; `--allow-deferrals` is the per-pass opt-in

Rejected alternative: `--terminal` on the gates.json command (the original sketch). Both reviewers
independently showed it fails open: `img2 doctor` validates command *form* only (placeholders,
metacharacters, argv0, referenced files — `commandFinding`) and `gate_runner.load_gates` validates
row shape only; neither can require a flag, and the command string is duplicated verbatim across
`gates.json`, `domain.json`, and three base-side docs. With strict-default, every forgotten or
copy-pasted flag yields today's known-safe noisy behavior instead of a lenient final door.
Flag name `--allow-deferrals` over `--phase pass`: §9 has no phase vocabulary, and a boolean that
names the loosening is self-documenting.

### D2 — Deferral keys are gate tokens, and the map is validated fail-closed

`deferredGates` and `failedGates` must share a vocabulary or no reader can diff them, and
`failedGates` is already gate tokens. Consequences: finish is `finishMaterialResponse` (metric and
token coincide), projection is `projection-coverage` (never `projection.coverage`). Unknown or
non-deferrable keys are named failures (`deferral-invalid:<key>`) — a typo must not defer nothing
while the producer believes it deferred something (same failure class as the flag polarity).

The full emitted-token vocabulary (17 tokens) is classified exhaustively in the spec; every token
is either in the closed deferrable set of three or explicitly never-deferrable.

### D3 — The deferrable set stays hardcoded in the tool

This was the one material reviewer disagreement, resolved by the lead in Reviewer A's direction.
B argued the review-scene fixture already owns threshold facts and the oracle re-record makes the
marginal cost zero. A's counter is decisive: `--scene` is a caller-supplied CLI path with a
default and no constraint, and `load_review_scene` passes extra keys unexamined — moving the
deferrable set there converts a constant only code review can change into one any `--scene`
argument can widen, reintroducing the fail-open class this change exists to kill. B's own
polarity reasoning treats caller-supplied input as untrusted; consistency decides it.
**Revisit trigger (recorded, not dropped):** per-family scenes exist AND scene selection is
resolved from the manifest rather than passed as a free CLI argument.

### D4 — Deferral truth table (total, no unspecified cells)

| deferred? | metric state | outcome |
|---|---|---|
| yes | null / absent | `deferredGates` (allow-deferrals mode only) |
| yes | present, failing | hard failure + `deferral-conflict:<token>` |
| yes | present, passing | evaluated normally; recorded in `spuriousDeferrals` |
| no | null / absent | failure (unchanged anti-laziness property) |

In strict mode, any `deferred` key at all is refused as `deferral-refused:<token>` (verdict
reject, exit 1); malformed shapes (non-object `deferred`, non-string reason, reason > 200 chars)
are structural errors (exit 2, `error` envelope). Length violations are hard errors, never
truncations — a truncated justification is a worse audit artifact than a refusal.
Deferring `projection-coverage` additionally requires `projection.required: true` present; an
omitted `projection` block keeps hitting non-deferrable `projection-evidence-missing`.

### D5 — Verdict vocabulary: keep `pass`; add scalars; both visibility planes

A `pass-deferred` verdict would convert every deferred pass into an `append_review.py` refusal —
the status-quo bug in a new costume (its `:373` keys on `verdict != "pass"`). Instead the report
(the only plane `append_review.py` sees) carries always-present `deferredGates` + `deferralCount`,
and the envelope (the only plane `gate_runner`/`run_gates.py` see) carries machine-generated
non-empty `reasons` (`"deferred: <token>"`) + `evidence.deferredGates`/`evidence.mode` — verified
compatible: `gate_runner.parse_verdict` coerces reasons only for non-pass. The scalar is named
`deferralCount`, not `deferred`, to avoid colliding with the input map's key. Agent prose stays in
the report file only.

### D6 — Provenance block: `mode`, `passId`, `pluginVersion`

Both invocations share `--out cs2-review.json`, so when the terminal gate never runs (the only
real run to date), the artifact at the canonical path is a lenient per-pass report
indistinguishable from a strict one. `mode: "strict" | "allow-deferrals"` makes the collision
self-describing. Rejected alternative: separate terminal `--out` — still leaves a stale per-pass
file at the name every reader reaches for. `passId` is echoed once at top level from the metrics
file (not per-deferral — one field cannot disagree with itself), answering the audit need the
rejected `until` field was reaching for. `pluginVersion` is read from `plugin.json` (mechanism
shipped in v0.1.1) so a `reviewHistory` shows which passes were judged under which rules, and a
stale install is detectable from any report. All three fold into the single oracle re-record.

### D7 — Strict-mode non-emptiness for `paintedRegions` and `criticalFeatures`, unconditional

Empty arrays iterate zero times and pass vacuously today — at every door. Strict mode requires
both arrays non-empty (`painted-regions-empty`, `critical-features-empty`). Unconditional (no
"when the family implies paint" qualifier): a CS2 skin is a paint job, family-conditional logic
was deliberately removed in v0.1.0, and non-emptiness (not set-equality against the knife scene's
identity lists) is what keeps this family-neutral. In allow-deferrals mode empty arrays keep
today's vacuous behavior — pre-bake there is legitimately nothing to list, and the per-pass row's
authority is advisory until the base attachment change lands.

### D8 — Why the per-pass row survives at all (conditional justification)

Terminal-only would be simpler. Kept because from material-pass onward the row is the only
per-iteration check on finish response, identity detail and painted-region coverage; catching a
finish defect at `plugin-gates` (after `action-ready`) costs whole-run rework. Stated honestly:
pre-material the row is a stricter re-check of the base's Tier-1 geometry numbers plus two
agent-self-certified orbit booleans (`maxOrbitCollapseRatio` is declared but never applied —
pre-existing, tracked), and until the base makes report attachment mandatory the row's enforcement
authority is zero by the live run's own demonstration. Its value becomes real when that base
change lands; this design keeps the row so that day needs no plugin change.

### D9 — Defense in depth, recorded

Layer 1: strict default (this change). Layer 2: drift-guard unit test reading both declaration
files and asserting `gates.json` has no `--allow-deferrals` while `domain.json` does (precedent:
the base's `gateRunnerArgv` parity guard). Layer 3 (tracked harness issue, out of scope):
`IMG2_GATE_PHASE=terminal` injected at `gate_runner`'s env construction — the only unforgeable
"this is the harness-run door" signal; when present it overrides `--allow-deferrals`. Residual
even with all three: an agent hand-running the tool outside `run_gates` can write a lenient report
to the canonical path — which is exactly what the `mode` stamp makes visible.

## Migration and rollback

- Forward: plugin directory replaces atomically on `img2 add --force`; gates execute from
  `$IMG2_HOME/plugins/cs2` only, so reinstall is a required operational step (in tasks). A
  workspace mid-run across the upgrade changes per-pass verdict rules between passes; the
  `pluginVersion` stamp in each report is the disambiguator.
- A v0.1.2-style metrics file (with `deferred`) against an installed v0.1.1: hard-rejects exactly
  as today (safe direction; the operator sees the old failure with no hint — acceptable, noted).
- Rollback to v0.1.1: every deferred pass rejects again (safe direction); no workspace artifact
  needs migrating.

## Risks and mitigations

- Agent never learns the `deferred` key → docs in the mandatory-read intake contract +
  spec-search-reachable review-gates doc (the load-bearing deliverable), plus the regression test
  pinned to the live run's inputs.
- New flag against stale installed tool → unrecognized-argument path now emits an `error` envelope
  on stdout before exit 2 (and `gate_runner` already preserves `stderr[-2000:]`).
- Oracle re-record hides an unintended change → task requires the fixture diff to show only the
  new fields; a strict-mode oracle companion covers the path the permissive oracle cannot.

## Gap matrix (debate outcome)

| Finding | Decision | Artifact |
|---|---|---|
| A-H1 / B-H5 fail-open `--terminal` | Accepted; polarity inverted, flag `--allow-deferrals` | D1, spec R1-R2, tasks |
| A-H2 / B-C4 bypass mis-described | Accepted; Why-now rewritten; base issue tracked | proposal Why-now, Non-scope |
| A-H3 / B-H2 terminal never executed | Accepted; scenario + captured-run acceptance criterion; "conditional on being reached" | proposal AC-3, spec R12, D6 |
| A-H4 / B-M2 vacuous arrays | Converged: drop `paintedRegion` from deferrable set AND strict-mode non-emptiness, unconditional | D4, D7, spec R8 |
| B-H1 byte-frozen oracle | Accepted; re-record same commit; always-emit `deferredGates` | D6, tasks |
| B-H3 nothing teaches `deferred` | Accepted as the load-bearing deliverable; both docs in scope; stale review-gates.md corrected | proposal §8, spec R11, tasks |
| B-H4 / A-M1 append_review is automated consumer | Accepted; `deferralCount` scalar; honest Breaking-changes sentence; base keying non-scoped | D5, proposal |
| A-M2 envelope reasons on deferred pass | Accepted; verified compatible with parse_verdict | D5, spec R9 |
| A-M3 four-cell table | Accepted; `deferral-conflict:<token>` adopted | D4, spec R5-R7 |
| A-M4 / B-M6 vocabulary + namespace | Merged: gate-token keys; 17-token exhaustive table; unknown key = failure | D2, spec R4 |
| A-M5 prose laundering | Accepted; machine reasons; string+200-char hard limit (error, not truncation) | D5, D4, spec R10 |
| B-M1 keep per-pass row | Accepted with A's amendment: justification written conditionally | D8 |
| B-M3 COLLECTED_FLOOR | Accepted | tasks |
| B-M4 base main still defective | Accepted; base-ref precondition in acceptance | proposal AC preconditions |
| B-M5 version stamp / rollback | Remedy accepted; A's rebut of the "cannot drift" premise recorded — drift-guard test stays regardless | D6, D9, tasks |
| A-L1 stale installs invisible | Accepted; reinstall task; `pluginVersion` stamp | D6, tasks |
| A-L2 uncalibrated thresholds carry pre-terminal verdict | Accepted; folded into one Non-scope acknowledgement | proposal Non-scope |
| A-L3 / B-L3 passId echo; exit-2 untested | Accepted; top-level once; exit-2 test cases added | D6, tasks |
| B-L1 README dead-code pointer | Accepted; canonical vocabulary named in tasks; split non-scoped | proposal Non-scope |
| B-L2 FINAL_STEPS ordering nit | Accepted; proposal corrected (after `emission-target`) | proposal |
| B rebut of A's "wrong in the large" | Accepted by lead: revision, not redesign | this document exists |
| A rebut of B-M5 premise (mtime = __pycache__) | Accepted by B; evidence struck, hazard stands | D9 |
| OQ(c) deferrable set location | Lead decision: hardcoded (A); B's dissent + revisit trigger recorded | D3 |
