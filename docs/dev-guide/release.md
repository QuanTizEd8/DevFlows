# Release Management

DevFlows releases workflows independently. A change to one workflow should not
force a release of every workflow in the repository.

## Versioning Policy

Each workflow uses SemVer with workflow-scoped tags:

- exact release: `workflow-id/vX.Y.Z` (always published)
- moving major: `workflow-id/vN` (published from `1.0.0` onward)

Moving **minor** tags are intentionally not published. Consumers pin an exact
release or a commit SHA, and from `1.0.0` may pin a moving major tag for
compatible updates.

### 0.x pre-completion contract

The catalog ships pre-1.0. Every workflow's release-please manifest version is
on a `0.x` line and its `devflow.yaml` `release.major` is `0`. While a workflow
is pre-1.0:

- Breaking changes are released as **minor** bumps, not major bumps. This is
  enforced by `bump-minor-pre-major: true` in
  `.github/release-please/config.json`, so a breaking change never accidentally
  promotes a workflow to `1.0.0`.
- Moving major tags are **not** published (the tag automation below is dormant
  by construction while the major is `0`).
- The 0.x line carries no cross-release compatibility promise.

### `release.major` semantics

`devflow.yaml`'s `release.major` records the **current released major version
line** for the workflow (an integer, `0` while pre-1.0). `task release-check`
cross-validates that it equals the major component of the workflow's
release-please manifest version, so the two can never silently diverge.

Promoting a workflow to `1.0` is a single deliberate change that, together:

1. sets the workflow's `.github/release-please/manifest.json` entry to `1.0.0`,
2. bumps `release.major` to `1` in its `devflow.yaml`, and
3. is reviewed as the moment the workflow's compatibility promise and moving
   major tag begin.

`task release-check` fails if steps 1 and 2 are not done together.

## Release Please

Release Please is configured in manifest mode:

- `.github/release-please/config.json`
- `.github/release-please/manifest.json`

Each active workflow must have a matching package entry. `task release-check`
validates that release-please configuration matches the active catalog.

## Changelogs

Per-workflow changelogs are managed by Release Please. Changelog paths are
configured per package in `.github/release-please/config.json`.

## Commit Messages

Use Conventional Commits. Prefer workflow scopes for workflow behavior changes:

```text
feat(pandoc): add working-directory scenario coverage
fix(pandoc): preserve checkout defaults
docs(pandoc): document extra image template path
test(pandoc): add hosted artifact assertions
```

Changes to shared tooling can use scopes such as `cli`, `docs`, `test`, or
`release`.

## Release Checks

Before opening a release-related pull request:

```bash
task release-check
```

The hosted release workflow runs Release Please after the configuration lands on
the default branch.

## Moving Tags

Release automation publishes immutable exact tags for every release. Once a
workflow reaches major `>= 1`, the release workflow additionally force-updates a
moving major tag `workflow-id/vN` to the newest release on that line (see
"Moving major tag automation" below). Moving minor tags are not published. While
a workflow is on `0.x`, no moving tag is published.
