# img2-cs2 quick start

The public npm installer lives in [`cli/`](cli/). Plugin implementation stays at the
repository root and is not included in the npm tarball. The npm package name is scoped
to `@img2threejs/cs2`; the global executable stays `img2-cs2`.

## Install the plugin

Requires Node.js >=18, Git, Python >=3.10, and Claude Code, Codex or OpenCode.
Hermes is not supported by the img2 plugin harness.

```bash
npx --yes @img2threejs/cs2 install --dry-run
npx --yes @img2threejs/cs2 install --yes
npx --yes @img2threejs/cs2 doctor
```

Installation creates the canonical img2 harness if missing, fetches `img2threejs/plugin-cs2`,
and links this plugin into detected hosts. It does not run a model or a reconstruction.
The pinned plugin source is the released commit `bee5766ec7dd5f336e3ac50f3da9b41e5dd16172`
(plugin version 0.1.2); use `--ref vX.Y.Z` to select a different plugin release explicitly,
or `update` to follow subsequent plugin tags.

## Develop this installer

```bash
npm --prefix cli install --ignore-scripts --no-package-lock
npm --prefix cli test
node cli/bin/cli.mjs install --dry-run
```

To run a globally installed CLI:

```bash
npm install -g @img2threejs/cs2
img2-cs2 install --yes
```

## Publish the first npm version

Use Node >=22.14 and npm >=11.15 for release setup. The npm account needs package write
access and account-level 2FA. Review the package contents; never publish from the plugin root.

The first manual bootstrap has no provenance: it runs outside the supported CI workflows
and `publishConfig.provenance=true` is overridden on the command line. Subsequent public-repo
GitHub OIDC releases keep `provenance: 'true'` in `cli-publish.yml` and `publishConfig`.

```bash
cd cli
npm test
npm pack --dry-run
npm publish --access public --ignore-scripts --provenance=false
cd ..
```

Then authorize the GitHub **caller** workflow filename, not the shared workflow filename:

```bash
npm exec --yes --package=npm@11 -- npm trust github '@img2threejs/cs2' \
  --repo img2threejs/plugin-cs2 --file cli-publish.yml --allow-publish --yes
```

The package must exist before this command can configure it. The npm website's trusted
publisher settings are equivalent. No npm write token is stored in Actions.

## Publish subsequent releases automatically

Bump `cli/package.json` and release notes, review and commit only intended changes, then
push a matching annotated `cli-vX.Y.Z` tag. For example, after bumping to `0.1.3`:

```bash
git tag -a cli-v0.1.3 -m 'CLI 0.1.3'
git push origin cli-v0.1.3
```

`.github/workflows/cli-publish.yml` tests, packs and publishes the exact tested tarball.
Stable CLI versions use npm's `latest` channel. Plugin source tags `vX.Y.Z` remain separate
from CLI release tags `cli-vX.Y.Z`. The same workflow also supports `workflow_dispatch`
with a `tag` input for manual CLI releases of an existing tag.

The plugin source `img2threejs/plugin-cs2` is public; no GitHub authentication or token is
required to fetch or install it. Restrict repository write and release-tag creation to
maintainers.

See [`cli/README.md`](cli/README.md) for CLI command details and
[npm trusted publishers](https://docs.npmjs.com/trusted-publishers/) for authentication.