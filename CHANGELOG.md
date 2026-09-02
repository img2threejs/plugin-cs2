# Changelog

All notable changes to **plugin-cs2** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] — 2026-09-02

### Changed

- **The review gate is phase-aware, strict by default.** With no flag (the terminal `plugin-gates`
  door), behavior is today's plus real teeth: a null metric fails, every `deferred` request is
  refused, and `paintedRegions`/`criticalFeatures` must be non-empty (previously an empty array
  passed those gates outright at every door). The per-pass row (`domain.json`) now carries
  `--allow-deferrals`, under which the metrics file may explicitly defer the three gates whose
  evidence the projection bake produces (`finishMaterialResponse`, `identityDetail`,
  `projection-coverage`) — previously those rejected every pass before material-pass on metrics
  that could not exist yet, teaching agents to route around a blocking gate. Deferral is
  declaration-only (prose grants nothing), fail-closed on unknown keys, and refused when the
  metric is present (`deferral-conflict`). OpenSpec change: `phase-aware-cs2-review`.
- Every report now carries a provenance block: `mode`, `passId`, `pluginVersion`,
  `deferredGates` (always present; empty means zero deferrals), `deferralCount`,
  `spuriousDeferrals`. The byte-frozen oracle fixture was re-recorded in this same change — the
  diff is exactly the new fields — and a permissive-mode oracle companion was added.
- A deferred pass names each deferral in the envelope `reasons` (`deferred: <token>`), so it is
  visible in the `img2.gate-run` aggregate, never a bare green.
- Unrecognized CLI arguments now emit an `error` envelope on stdout before exit 2 (a newer
  `gates.json` against a stale installed tool stays diagnosable).
- `grimoire/intake/cs2_intake_contract.md` documents the metrics-file schema including `deferred`
  with a worked example; `docs/cs2/review-gates.md` rewritten (it described pre-extraction
  `forge/…` paths and a family gate removed in 0.1.0).

### Rollback

Reverting to 0.1.1 makes every deferred pass reject again — the safe direction; no workspace
artifact needs migrating. Reports written by 0.1.1 lack the provenance block; `pluginVersion`
distinguishes them.

## [0.1.1] — 2026-09-02

### Fixed

- **The blocking review gate can pass now.** `tools/cs2_review.py` speaks a single
  `img2.gate-verdict` envelope on stdout instead of dumping its report there — as installed at
  0.1.0 the runner read the report dump as a malformed envelope, so the gate returned `error` on
  every run, including against the plugin's own passing oracle fixture. The report lives in `--out`.
- The detail floor travels through `qualityFloors` alone, so the base's raise-only clamp governs it
  on every path instead of being bypassed via `assessmentPatch`.
- `steps.json` no longer duplicates the domain track that `domain.json` declares.
- The `cs2` spec-search collection restores the generic `core_3d` records and ships the
  documentation file its search profile declares.

### Added

- `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` and `LICENSE`.

## [0.1.0] — 2026-08-25

First release. Extracted from the `img2threejs` base skill, which no longer carries any CS2 knowledge.

### Added

- **The plugin itself.** A typed capability edge `image → cs2-skin-spec`, four setup steps anchored
  before the base's `local-spec-search`, and one blocking review gate before `ai-review-recorded` in
  every correction pass.
- **The intake contract** (`grimoire/intake/cs2_intake_contract.md`) as a step the model must read
  completely before authoring a manifest, carried as an `actor: agent` row rather than a command.
- **A machine-checked manifest** (`tools/cs2_manifest.py`) recording `componentAdapter` when this
  plugin has geometry for the family.
- **The finish and wear rulebook** (`grimoire/build/cs2_finishes.md`) and the spec recipe
  (`tools/cs2_spec_template.py`), published as a `spec-augmentation-v1` artifact the base **pulls**
  during spec authoring rather than the plugin pushing anything.
- **A blocking review gate** (`tools/cs2_review.py`) with a fixed review scene and golden thresholds,
  deliberately stricter than the base's general fidelity gate.
- **The CS2 evidence corpus** as a contributed spec-search collection, reachable through a vouched
  `content_root` without relaxing the containment guard.
- **Optional exactness upgrades**, each degrading gracefully to the image-only path:
  `locate_cs2_vpk.py`, `extract_cs2_textures.py`, `fetch_cs2_metadata.py`.
- **A byte-equality oracle** (`tests/fixtures/oracle-talon/`) replaying a completed Talon
  reconstruction, and `tests/test_suite_integrity.py` asserting the collected test count against a
  recorded floor.
- Per-family anatomy for knives, gloves, pistols, rifles, SMGs, snipers and heavy weapons.

### Changed

- **Every CS2 family is served, and only geometry is withheld.** A family without an adapter records
  `geometrySource: agent-inferred` and the run continues under the rest of the contract, rather than
  being refused. Knife and pistol have adapters; the others are inferred from their anatomy pages.
- **The plugin consumes the base's `admission.json` and `probe.json` artifacts** instead of importing
  base code, satisfying the contract's no-`forge.*`-import rule.

### Removed

- **The `--cs2` flag and name-based recognition.** The domain is declared (`--profile cs2`), never
  inferred from the target's name. The base skill previously applied CS2's quality floors to any target
  whose name contained one of seventeen keywords, `"fade"` among them — a match on `"fade"` alone was
  enough. Name similarity is not evidence (`PLUGIN_CONTRACT.md` §13).
- **The item-family gate.** An unsupported family previously blocked the run; it now proceeds with an
  honest geometry source.

### Known limits

- Paint seed and float are not recoverable from an image; anything derived from them is approximated
  and must be reported as such.
- Adapter geometry exists for knife (11 subtypes) and pistol (glock-18) only.
- `detect_cs2.py` is a heuristic for triage and is never used for routing.

[0.1.2]: https://github.com/img2threejs/plugin-cs2/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/img2threejs/plugin-cs2/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/img2threejs/plugin-cs2/releases/tag/v0.1.0
