# @img2threejs/cs2

Public installer for the img2 plugin **cs2**, sourced from `img2threejs/plugin-cs2`.
This package contains the installer only; plugin implementation is fetched separately.
The global executable name remains `img2-cs2`; only the npm package name is scoped.

## Quick start

Requires Node >=18, Git, Python >=3.10, and Claude Code, Codex or OpenCode.

```bash
npx --yes @img2threejs/cs2 install --dry-run
npx --yes @img2threejs/cs2 install --yes
npx --yes @img2threejs/cs2 doctor
```

Or install the CLI globally and invoke the unscoped binary:

```bash
npm install -g @img2threejs/cs2
img2-cs2 install --yes
img2-cs2 doctor
```

The shared runtime is `@img2threejs/img2`, pinned to exactly `0.4.0`. Installation
bootstraps the canonical harness under `$IMG2_HOME` (default `~/.img2`) and links this
plugin into detected hosts. Installing this npm package alone does not install a skill.
The harness does not support Hermes. Model/provider and reconstruction prerequisites
remain the plugin's responsibility; installation is not reconstruction acceptance proof.

This installer's plugin source pin is the released commit
`bee5766ec7dd5f336e3ac50f3da9b41e5dd16172` (plugin version 0.1.2).
CLI versions are independent of plugin versions; new plugin development is fetched
separately and is not included in this npm package.

## Commands

```text
img2-cs2 install [--ref <vX.Y.Z|40-char SHA>] [--home <absolute path>] [--yes] [--force] [--dry-run]
img2-cs2 update [--home <absolute path>] [--yes] [--check]
img2-cs2 remove [--home <absolute path>] [--yes]
img2-cs2 doctor [--home <absolute path>] [--json]
img2-cs2 version [--json]
img2-cs2 help
```

`--dry-run` performs no downloads, subprocesses or writes. `--force` changes only this
plugin's registered ref; local links and registrations from another source are protected.
An explicit `--ref` overrides the CLI's metadata pin. Without a pin, install chooses the
newest semantic plugin tag, or warns and uses HEAD if untagged. Use `update` to check or
apply subsequent semantic plugin releases. CLI and plugin versions are independent.

`doctor` audits the entire installed harness, including other plugins.
Exit codes: `0` success, `1` failure, `2` refused, `3` confirmation requires a terminal.

## Installer development

From the repository root:

```bash
npm --prefix cli install --ignore-scripts --no-package-lock
npm --prefix cli test
npm --prefix cli pack --dry-run
```

The repository's `CLI_QUICKSTART.md` documents initial publication, trusted publisher
configuration and automatic `cli-vX.Y.Z` releases.

## Release notes

- **0.1.2**: initial public installer-only npm package `@img2threejs/cs2`. Plugin source
  pinned to released commit `bee5766e` (plugin 0.1.2); runtime `@img2threejs/img2@0.4.0`.
  Global executable remains `img2-cs2`.