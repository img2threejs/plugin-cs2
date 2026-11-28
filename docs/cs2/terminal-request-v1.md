# Terminal request ABI v1 (plugin 0.3.0)

This is a **paired core/plugin ABI change**, not rolling compatibility and not
standalone terminal acceptance. Core must pin the exact reviewed plugin commit,
manifest and gate row; old/new mismatches fail closed. No provider SHA is invented
by this document. Low-level replay remains non-authorizing.

## Exact gate declaration

```text
python3 {plugin_dir}/tools/cs2_review.py --terminal-request .img2/cs2-terminal/gate-request.json
```

The fixed global request is discovery only. Core's final verifier instead invokes
its authenticated context's immutable per-run request with `--workspace CHILD`:

```text
.img2/cs2-terminal/run-<32 lowercase hex>/gate-request.json
```

Only those two request path forms are admitted. An explicit descriptor's parent
must match the run named by both evidence bindings. Absolute paths, traversal,
unknown filenames, symlinks and non-regular files are refused.

## Exact request schema

```json
{
  "kind": "img2.cs2-terminal-request",
  "version": 1,
  "inputs": {
    "path": ".img2/cs2-terminal/run-0123456789abcdef0123456789abcdef/inputs.json",
    "sha256": "<64 lowercase hex>"
  },
  "scene": {
    "path": ".img2/cs2-terminal/run-0123456789abcdef0123456789abcdef/scene.json",
    "sha256": "<64 lowercase hex>"
  }
}
```

No extra keys. Version is integer 1, not bool/float/string. Bindings contain exactly
`path` and `sha256`, name the same canonical run and exact filenames, and bind
current regular-file bytes. Duplicate JSON keys and non-finite constants refuse.

Core is responsible for immutable per-run descriptor publication before binding
its semantic context. The global locator contains the exact same bytes as that
run descriptor. Plugin global discovery reads both and requires equality; explicit
per-run invocation never reads the global locator. Core must publish the global
locator atomically without following symlinks; the plugin neither publishes it nor
treats it as host approval/current authoritative run state.

## Replay and sole report publisher

The plugin reconstructs metrics and scene from bound inputs, compares the strict
scene with reconstructed typed canonical JSON, enforces frozen thresholds and no
deferrals, and rechecks the descriptor, inputs, scene and underlying evidence.

The only report destination is `<same-run>/gate-review.json`. Its complete bytes
are exactly `serialize_json(replay["report"])`, without timestamps or extra claims.
**Plugin is the sole publisher**: core must not prewrite this file at cutover.
Publication is atomic, no-clobber and anchored through symlink-free directories.
Existing identical report bytes are read-only replay; different bytes, symlinks or
non-regular files refuse. Unrelated root `cs2-review.json` and old runs stay intact.

`--manifest`, `--metrics`, `--prepare-scene`, `--scene`, `--out` and
`--allow-deferrals` cannot accompany request mode. The old `--terminal-inputs`
review CLI mode was removed, not retained as an authority-compatible alias.
Per-pass evaluation and `cs2_terminal.py --inputs ... --inputs-sha256 ...` remain
separate interfaces; neither can substitute for this gate or authenticated review.

## Exact verdict evidence

Outer envelope remains `img2.gate-verdict`, version 1, gate `cs2-review`, plugin
`cs2`, with pass/fail/error and exit 0/1/2. A measured pass or reject binds:

```text
artifact: {path, sha256}
request: {path, sha256}  # immutable per-run descriptor, even through global discovery
inputs: {path, sha256}
scene: {path, sha256}
report: {path, sha256}   # derived gate-review.json
scope: "mechanical-replay-only"
terminalAuthority: false
verdict: "pass" | "reject"
action: <exact replay action>
mode: "strict"
deferredGates: []
```

Errors carry no claimed evidence/authority. Core must verify every binding and
status/verdict/action/mode/deferral value against its authenticated context and
expected run, require literal boolean `terminalAuthority:false`, independently
recapture/replay and revalidate provider/runtime/current grant and quality journal.
A global locator edit cannot replace the context-selected request.

Non-routed host evidence remains evidence-only. Workspace JSON, fabricated capture
records, a callable or `host-reviewed` text cannot mint host or routed authority.
There is no authored-metrics fallback and no standalone terminal-acceptance claim.

## Evidence limits

Fictional lantern protocol fixtures generate their own PNGs and self-contained
colored-cube GLB. Their capture records explicitly say synthetic/not rendered.
They prove path/digest/schema/replay behavior, not a real render, source calibration,
provider provenance, authenticated quality review or paired-core acceptance.
Original historical/shared-scene/full gates remain separately unverified.
