---
name: cs2
version: 0.1.0
description: Counter-Strike 2 weapon and glove skin reconstruction — intake contract, authoritative classification, finish and material recipes, and a blocking review gate.
---

# CS2 domain plugin

Upgrades an `img2threejs` run for a Counter-Strike 2 skin. Without this plugin installed, the base
skill treats a CS2 skin as an ordinary hard-surface object and reconstructs it by inference. With it,
the run gains an authoritative intake contract, a machine-checked manifest, the finish and wear
rulebook, and a blocking review gate — none of which the base skill can improvise.

The base skill stays the entry point. This plugin does not replace it and cannot run alone.

## When this applies

A run whose target is a CS2 weapon skin, knife, or glove. **Declare it** — `--profile cs2` on the
state file and `--cs2` when authoring the spec. It is not inferred from the target's name: a target
called `"AK-47 | Redline"` does not self-identify, by design. Name similarity is not evidence
(`PLUGIN_CONTRACT.md` §13), and the base skill previously applied CS2's quality floors to anything
whose name happened to contain one of seventeen keywords, `"fade"` among them.

## What it contributes

Three setup steps, spliced before the base's `local-spec-search`, and one blocking gate in every
correction pass.

| Step | Actor | What it does |
|---|---|---|
| `cs2-contract-read` | agent | Read `grimoire/intake/cs2_intake_contract.md` **completely** before creating or validating the manifest. It is a contract, not a reference. |
| `cs2-authoritative-classification` | agent | Obtain an authoritative family/subtype record into `classification.json`. Guessing the subtype from the image is the failure this step exists to prevent. |
| `cs2-manifest` | program | `tools/cs2_manifest.py` builds and validates `cs2-intake.json`. Its `state` must be `proceed` or `fallback` before authoring. |
| `cs2-review` (gate) | program | `tools/cs2_review.py` produces a machine-readable verdict. **Blocking**: a failed verdict stops `continue` even when the global fidelity score passes. |

It also contributes the `cs2` evidence collection to the base's local spec search.

## Hard rules

- **Read the intake contract completely before the manifest.** Both the contract and the base
  skill's checklist require it; a manifest authored without it is not admissible.
- **A failed `cs2-review` blocks continuation.** Do not proceed on a global score alone. The review
  is deliberately stricter than the general fidelity gate because a wrong subtype or a wrong finish
  reads as a different item entirely.
- **Paint seed and float are not recoverable from an image.** Record pattern placement and wear as
  approximated, never as measured.
- **The subtype is authoritative or it is unknown.** A Talon has no crossguard; a Karambit does.
  Reporting a part as not-applicable is correct, inventing one is not.

## Reference material

`docs/cs2/` — technical mapping and vocabulary. `docs/cs2-anatomy/` — per-family anatomy (knives,
gloves, pistols, rifles, SMGs, snipers, heavy). `grimoire/intake/cs2_intake_contract.md` — the intake
contract. `grimoire/build/cs2_finishes.md` — finish routes and the wear rulebook.

## Tests

`tests/` runs standalone: `python3 -m unittest discover -s tests -p 'test_*.py'`. Includes a
byte-equality replay of a completed reconstruction (`tests/fixtures/oracle-talon/`) that fails if the
review output drifts by a single byte.
