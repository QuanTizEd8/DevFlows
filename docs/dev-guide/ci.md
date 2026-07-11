# Continuous Integration

DevFlows CI protects both the project tooling and the reusable workflows.

## Main CI Workflow

`.github/workflows/devflows-ci.yaml` runs validation in the devcontainer:

```bash
pixi install
task lint
task test
task propagation-check
```

This covers static checks, generated-file drift, unit tests, formatting,
workflow syntax, shell linting, and security findings. On pull requests it also
runs the shared-generator propagation guard (see the release guide). The job
reuses the prebuilt devcontainer image/cache published by
`devflows-devcontainer.yaml`, and a per-ref concurrency group cancels superseded
runs.

## Hosted Scenario Workflows

One `.github/workflows/devflows-scenarios-<id>.yaml` file per catalog workflow
is generated from workflow metadata. Each calls its promoted reusable workflow
and then runs assertion jobs. The suite is partitioned per owning workflow so no
single file crosses the size GitHub startup-rejects; every file shares the same
`pull_request` / `push` trigger, so GitHub runs them all in parallel on one
event and total coverage is unchanged. Hosted scenario tests are the right place
to verify behavior that needs real GitHub services.

For example, Pandoc hosted scenarios upload generated files as artifacts and
then assertion jobs download those artifacts and inspect their contents.

## Local Scenario Workflows

One `.github/workflows/devflows-scenarios-<id>.local.yaml` file per workflow
with local scenarios is generated for local `act` runs:

```bash
task scenarios-local
```

Local scenarios are intended for fast feedback. They should avoid hosted-only
services unless `act` can emulate them reliably.

## Docs Workflow

`.github/workflows/devflows-docs.yaml` generates reference pages and builds
Sphinx output. Pull requests build the docs to catch Sphinx errors; only pushes
to `main` configure GitHub Pages and deploy. Source docs live under `docs/`,
while `docs/reference/` is ignored build output created before Sphinx runs.

## Release Workflow

`.github/workflows/devflows-release.yaml` runs Release Please and, once a
workflow reaches major `>= 1`, moves its `<id>/v<major>` tag. Release behavior
is driven by workflow metadata and `.github/release-please` configuration. See
the {doc}`release guide <release>` for the token setup and runbook.

## CodeQL Workflow

`.github/workflows/devflows-codeql.yaml` runs CodeQL analysis over the Python
code on push, pull requests, and a weekly schedule. It uses the default Python
analysis (no custom query packs) with every action SHA-pinned.

## Devcontainer Image Workflow

`.github/workflows/devflows-devcontainer.yaml` dogfoods the catalog: it calls
the repository's own `build-devcontainer` reusable workflow to prebuild and
publish the CI/development devcontainer image plus a registry build cache to
GHCR. It runs on `.devcontainer/**` changes on `main`, weekly, and on demand;
`devflows-ci.yaml` and `devflows-docs.yaml` reuse the cache.

## Adding New CI Coverage

Prefer adding scenario metadata to `devflow.yaml` over hand-writing one-off CI
jobs. The generated scenario workflow keeps test behavior discoverable from the
workflow metadata and reduces drift between workflows.
