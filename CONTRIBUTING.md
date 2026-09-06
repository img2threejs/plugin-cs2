# Contributing to plugin-cs2

This is a domain plugin for [img2threejs](https://github.com/img2threejs/img2threejs). It carries the
Counter-Strike 2 knowledge the base skill deliberately does not have. Contributions that make that
knowledge more exact — or more honest about its limits — are welcome.

Read [`README.md § Customising it`](README.md#customising-it) first; it covers the common changes and
where they go.

## The two rules that decide whether a change belongs here

**1. The base skill must keep working without this plugin.** Not degraded into uselessness — working. A
CS2 skin reconstructed by inference is less exact, and that is the intended trade. If a change here
would make the base worse, or make the plugin load-bearing, it belongs somewhere else.

**2. This plugin can make the run stricter or better-informed. Never looser.** It cannot remove a base
gate, lower a base quality floor, reorder base steps, or substitute a base command — the harness
enforces most of this and the augmentation merge enforces the rest. A change that reaches for any of
those is a change to the base skill or the contract, not to this repo.

## Good first areas

- **Anatomy pages** (`docs/cs2-anatomy/`). The highest-value, lowest-risk contribution. A subtype whose
  parts are described precisely — *including the parts it does not have* — is a subtype the run stops
  inventing geometry for.
- **A subtype for an existing adapter.** `tools/cs2_adapters.py`, plus its anatomy page.
- **Finish routes and wear behaviour** (`grimoire/build/cs2_finishes.md`).
- **Vocabulary records** (`docs/specs/vocabulary/*.jsonl`) that the corpus indexes.
- **A new family adapter**, when inference is measurably not good enough for that family — not
  preemptively.

## Honest limits, and how to write about them

- **Paint seed and float are not recoverable from an image.** Anything derived from them is
  approximated. Say so in the output, not only in the commit message.
- **The subtype is authoritative or it is unknown.** A Talon has no crossguard; a Karambit does.
  Reporting a part as not-applicable is correct; inventing one is not, and a contribution that makes
  the run guess a subtype will be rejected however good the geometry is.
- **`detect_cs2.py` is triage, never routing.** Routing is by declared domain. Do not wire detection
  into a decision path.

## Development

```bash
python3 -m pytest tests -q                              # 36 passed
python3 -m unittest discover -s tests -p 'test_*.py'    # same suite, stdlib runner
img2 add --link .                                       # install this checkout, no clone
img2 doctor                                             # must be zero findings
```

- **Standard library only on the required path.** The four optional exactness tools may shell out to a
  binary you supply; nothing on the required path may.
- **The suite must pass standalone**, without the base skill's test tree. That is the property that
  makes this a plugin rather than a fork.
- **`img2 doctor` must report zero findings**, not "only warnings".
- Tools take `--workspace`, defaulting to the current directory — never the checkout root.
- Set `actor` explicitly on every prose step row. The default is `program`, and a prose sentence handed
  to an executor is how `Read the contract` once resolved to `/usr/bin/read` and exited 0.
- No emojis in source, docs, or generated output.

## The oracle will fail you on purpose

`tests/test_cs2_oracle_replay.py` asserts **byte equality** against a completed Talon reconstruction in
`tests/fixtures/oracle-talon/`. Any change to the review output — a threshold, a rounding, a field
order — fails it.

That is the point. When it fails:

1. Work out whether the new output is *more correct* or merely *different*.
2. If merely different, fix your change.
3. If more correct, re-freeze the fixture **in its own commit**, and say in the message why the new
   verdict is the right one. A re-freeze buried inside a feature commit is how an oracle stops being an
   oracle.

`tests/test_suite_integrity.py` asserts the **collected** test count against a recorded floor. Assert
collected, never the run count: the run/skipped split depends on which optional toolchains are
installed, so the same tree gives different splits on different machines.

## Never read a test's own stdout as a verdict

A test exercising a failure path prints its own `FAILED:` line at column 0. Anchor on `Ran N tests` and
the line after it, or use the exit code — nothing a test prints can forge that.

## Before you open an issue

- Search existing issues first.
- For a bug: the exact command, the manifest or verdict JSON, expected versus actual. **Never attach
  extracted game textures, a `_img2_local.py`, or private reference images.**
- For a proposal: the problem, the observable outcome, and which of the two rules above it respects.

## Assets

This repository ships no Counter-Strike 2 assets and must never start. See [SECURITY.md](SECURITY.md).

## Publishing to npm

1. Bump the version in **both** `plugin.json` and `package.json` — CI's `version-sync` job fails the build if they disagree.
2. Update `CHANGELOG.md`.
3. Commit the bump.
4. Tag the commit `vX.Y.Z` (matching the new version) and push the tag.
5. The `publish` workflow picks up the tag, re-checks the version match, and runs `npm publish --provenance --access public` against `@img2threejs/plugin-cs2`.

## License

By contributing you agree your contributions are licensed under Apache-2.0, the same as this project.
