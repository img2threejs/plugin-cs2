# Tasks: phase-aware-cs2-review

## 1. Tool changes (`tools/cs2_review.py`)

- [x] 1.1 Split the `_failed_threshold` call sites so "metric missing/non-numeric" and "metric
      present but below/above threshold" are distinguishable outcomes.
- [x] 1.2 Add the hardcoded deferrable-set constant (`finishMaterialResponse`, `identityDetail`,
      `projection-coverage`) and `--allow-deferrals`; implement the D4 truth table including
      `deferral-refused:<token>` (strict), `deferral-invalid:<key>`, `deferral-conflict:<token>`,
      and `spuriousDeferrals`.
- [x] 1.3 Validate the `deferred` map shape: object, plain-string values, ≤ 200 chars; violations
      exit 2 with an `error` envelope naming the cause (never truncate).
- [x] 1.4 Enforce `projection.required: true` as a precondition for deferring
      `projection-coverage`; keep `projection-evidence-missing` non-deferrable.
- [x] 1.5 Strict-mode non-emptiness for `paintedRegions` and `criticalFeatures`
      (`painted-regions-empty`, `critical-features-empty`), unconditional.
- [x] 1.6 Add the always-present report fields: `deferredGates`, `deferralCount`,
      `spuriousDeferrals`, `mode`, top-level `passId` echo, `pluginVersion` (read from
      `plugin.json`).
- [x] 1.7 Envelope: machine-generated `reasons` (`deferred: <token>`) plus `evidence.deferredGates`
      and `evidence.mode` on a deferred pass; agent prose never reaches the envelope.
- [x] 1.8 Wrap argument parsing so an unrecognized argument emits an `error` envelope on stdout
      before exit 2.

## 2. Declarations

- [x] 2.1 Add `--allow-deferrals` to the `cs2-review` passStep command in `domain.json`;
      `gates.json` stays unchanged (strict).

## 3. Tests (`tests/`)

- [x] 3.1 Per-pass mode: deferred+absent defers; deferred+null defers (live shape); null without
      deferral still fails (the anti-laziness negative test); `deferred: {}` behaves as absent.
- [x] 3.2 Vocabulary: non-deferrable token refused (`deferral-invalid:silhouetteIoU`); typo'd key
      refused with the offending name; metric-path spelling (`projection.coverage`) refused.
- [x] 3.3 Truth-table: deferred+present+failing → `deferral-conflict:<token>` + reject;
      deferred+present+passing → evaluated normally, listed in `spuriousDeferrals` only.
- [x] 3.4 All three deferrable gates deferred with passing geometry → pass, `failedGates: []`,
      `len(deferredGates) == 3`; geometry/orbit gates provably always evaluated.
- [x] 3.5 Regression test pinned to the live run: `test-e2e-20260902`'s preserved
      `cs2-review-inputs.json` + `cs2-intake.json` (copied into `tests/fixtures/`), with a
      `deferred` block naming the three tokens → pass; and verbatim without `deferred` (prose-only)
      → reject with the same three gates.
- [x] 3.6 Projection: omitted `projection` block with a declared `projection-coverage` deferral →
      `projection-evidence-missing`, reject.
- [x] 3.7 Strict mode: any `deferred` key → `deferral-refused:<token>`, exit 1; deferral-shaped
      inputs of 3.1 → reject with deferrals named as failures; complete passing metrics with
      non-empty arrays → pass, exit 0 (no regression); `paintedRegions: []` →
      `painted-regions-empty`; `criticalFeatures: []` → `critical-features-empty`.
- [x] 3.8 Envelope/CLI: deferred pass prints exactly one parseable `img2.gate-verdict`
      (`status: "pass"`, machine reasons, `evidence.deferredGates`, nothing else on stdout);
      unknown flag → `error` envelope then exit 2; missing metrics file → exit 2 with the file
      named (closes the previously untested exit-2 path); malformed `deferred` shapes (list,
      string, number, non-string value, >200-char reason) → exit 2 `error` envelope.
- [x] 3.9 Declaration drift guard: unit test reading `gates.json` and `domain.json`, asserting the
      flag placement (gates strict, domain lenient).
- [x] 3.10 Re-record `tests/fixtures/oracle-talon/cs2-review.json` in the same commit as 1.6; add
      an assertion that the fixture diff is exactly the new fields (`deferredGates: []`,
      `deferralCount: 0`, `spuriousDeferrals: []`, `mode`, `passId`, `pluginVersion`); extend
      `test_the_oracle_records_a_passing_verdict` with `deferredGates == []`.
- [x] 3.11 Add a strict-mode oracle companion so the strict path has oracle coverage (the existing
      replay exercises only the permissive invocation).
- [x] 3.12 Raise `COLLECTED_FLOOR` in `tests/test_suite_integrity.py` to the new collected count
      and state the number in this file when done: **70** (was 36).

## 4. Documentation

- [x] 4.1 `grimoire/intake/cs2_intake_contract.md`: document the metrics-file schema — `deferred`
      object, gate-token vocabulary, the closed deferrable set, reason limits, strict-vs-per-pass
      semantics, and a worked example. (Canonical vocabulary source: the scene fixture's
      `thresholds` plus the report's gate tokens — NOT `tools/cs2_review_contract.py`, which the
      gate never imports.)
- [x] 4.2 Rewrite `docs/cs2/review-gates.md`: plugin-resident paths (no `forge/…`), remove the
      family/adapter gate v0.1.0 deleted, document modes, deferral contract, and the provenance
      block.
- [x] 4.3 CHANGELOG entry: the behavior change, the oracle re-record and why, the rollback note
      (reverting to v0.1.1 makes deferred passes reject again; no artifact migration).

## 5. Release and delivery evidence

- [x] 5.1 Bump `plugin.json` to 0.1.2; tag `v0.1.2`; push with tag.
- [x] 5.2 (doctor: ok, 3 plugins) Reinstall: `img2 add img2threejs/plugin-cs2 --ref v0.1.2 --force`; `img2 doctor` green.
      (Gates execute from `$IMG2_HOME/plugins/cs2` only — without this step nothing changes at
      runtime.)
- [x] 5.3 (captured: scratchpad/accept-012/cs2-review.json + perpass-envelope.json) Capture acceptance artifact 1: a real pre-material per-pass run on a workspace (base =
      img2threejs `lab/cs2-plugin` @ ≥ 5ca9f81) producing `verdict: "pass"` with the three
      deferrals named and `mode: "allow-deferrals"`.
- [x] 5.4 (captured: scratchpad/accept-012/gate-run-aggregate.json — first real execution; blocking-stop verified via run_gates.py) Capture acceptance artifact 3: a real `run_gates.py --workspace .` execution at
      `plugin-gates` on a workspace whose metrics carry a `deferred` block → `img2.gate-run` with
      `cs2-review` `status: "fail"`, deferral named in `reasons`, `stopped: true` (first-ever real
      execution of this path).
- [ ] 5.5 Capture acceptance artifact 2 (best-effort, contract-driven): a `reviewHistory` entry
      with `domainReview` populated via `--domain-review-json` and no override prose in
      `visualEvidence.notes`.

## 6. Tracked follow-ups filed outside this change

- [x] 6.1 (img2threejs#122) Base issue (img2threejs): make `--domain-review-json` mandatory when the workspace
      resolves a domain profile (the non-attachment bypass observed live).
- [x] 6.2 (img2#1) Harness issue (img2-harness): inject `IMG2_GATE_PHASE=terminal` in `gate_runner`'s child
      env; when present it overrides `--allow-deferrals` (defense-in-depth layer 3).
- [x] 6.3 (plugin-cs2#1) Plugin issue: `maxOrbitCollapseRatio` declared but never applied; the
      `cs2_review_contract.py` / scene-fixture split and the README `GOLDEN_THRESHOLDS` pointer.
