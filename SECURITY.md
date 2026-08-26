# Security

## Reporting

Open a private security advisory on this repository, or contact the maintainers directly. Do not open a
public issue for anything exploitable.

Include what you ran, what happened, and what you expected. A reproduction against a clean
`$IMG2_HOME` is worth more than a description.

## Threat model

The harness contract states it plainly, and it applies to this plugin: **a plugin is arbitrary code the
agent will later execute in your workspace.** `img2 add` pins a `resolvedSha`, records a registry row,
and links under a harness-owned name — *"it cannot make the code safe, only make what runs identifiable
and reproducible."*

What that means for this plugin specifically:

- The harness **never runs this plugin's tests or imports its code** during `add`, `doctor` or `sync`.
  Validation is static. Code runs only when the pipeline reaches a step that invokes it.
- Every command in `steps.json` and `gates.json` is checked against a closed placeholder set
  (`{plugin_dir}`, `{workspace}`, `{image}`) and refused if it contains a shell metacharacter. Nothing
  here runs through a shell.
- Tools take `--workspace`, defaulting to the current directory — **never** the checkout root. A tool
  that writes into the checkout is writing into somebody's git working tree.

## Game assets — the rule that matters most here

**This repository ships no Counter-Strike 2 assets, and must never start.** No `.vpk`, `.vtf`, `.vmt`,
`.tga`, `.dds`, or extracted textures. Verified as a property of the tree, not a promise:

```bash
git ls-files | grep -iE '\.(vpk|vtf|vmt|png|jpg|tga|dds|bin|glb)$'   # must return nothing
```

`tools/extract_cs2_textures.py` reads **your own legal install** and writes into your workspace. Its
output is yours and stays local. Do not commit it here, do not attach it to an issue, and do not
redistribute it. Counter-Strike 2 and all related marks and assets are the property of Valve
Corporation.

The plugin's own reference material — anatomy pages, vocabulary, finish rulebook — is original
description, not extracted content.

## Network egress

One tool makes network requests, and it is optional:

| Tool | Destination | When |
|---|---|---|
| `fetch_cs2_metadata.py` | the CSGO-API skins index, over `urllib.request.urlopen` with a 30 s timeout | only when you invoke it |

It is **never on a required path**. Its output is an input to review, not a gate. It never guesses: a
no-match or an ambiguous multi-match is an error, not a silent pick — which matters, because a silently
wrong paint index would propagate into the spec as though it were measured.

Nothing else in this plugin opens a socket. The required path is offline.

## External binaries

`tools/extract_cs2_textures.py` shells out to a Source2Viewer-CLI binary **you supply and trust**. The
plugin does not download it. Every failure mode — no VPK, no binary, subprocess error, non-zero exit —
returns `{"status": "fallback", "reason": …}` so the pipeline falls back to the image-only path rather
than producing a wrong answer.

## Secrets

This plugin requires no credentials, reads no environment secrets, and writes none. If you find any
value that looks like a token in this tree, treat it as a defect and report it.

`_img2_local.py` is machine-local by construction — it holds an absolute path to your harness core —
and is gitignored. Do not commit it, and do not paste its contents into an issue.

## Supported versions

Security fixes land on the latest tag. There is no long-term support branch.

| Version | Supported |
|---|---|
| 0.1.x | yes |
| < 0.1 | no |
