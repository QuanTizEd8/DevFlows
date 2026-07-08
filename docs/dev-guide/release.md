# Release Management

DevFlows releases workflows independently. A change to one workflow should not
force a release of every workflow in the repository.

## Versioning Policy

Each workflow uses SemVer with workflow-scoped tags:

- exact release: `workflow-id/v1.2.3`
- moving minor: `workflow-id/v1.2`
- moving major: `workflow-id/v1`

Consumers should use moving major tags for compatible updates, exact tags for
reproducibility, or commit SHAs for maximum assurance.

## Release Please

Release Please is configured in manifest mode:

- `.github/release-please/config.json`
- `.github/release-please/manifest.json`

Each active workflow must have a matching package entry.
`pixi run release-dry-run` validates that release-please configuration matches
the active catalog.

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
pixi run release-dry-run
```

The hosted release workflow runs Release Please after the configuration lands on
the default branch.

## Moving Tags

Release automation should publish immutable exact tags and update moving major
and minor tags. Consumers that need stronger guarantees should use exact tags or
commit SHAs.
