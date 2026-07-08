# Continuous Integration

DevFlows CI protects both the project tooling and the reusable workflows.

## Main CI Workflow

`.github/workflows/devflows-ci.yaml` runs validation in the devcontainer:

```bash
pixi install
pixi run lint
pixi run test
```

This covers static checks, generated-file drift, unit tests, formatting,
workflow syntax, shell linting, and security findings.

## Hosted Scenario Workflow

`.github/workflows/devflows-scenarios.yaml` is generated from workflow metadata.
It calls promoted reusable workflows and then runs assertion jobs. Hosted
scenario tests are the right place to verify behavior that needs real GitHub
services.

For example, Pandoc hosted scenarios upload generated files as artifacts and
then assertion jobs download those artifacts and inspect their contents.

## Local Scenario Workflow

`.github/workflows/devflows-local-scenarios.yaml` is generated for local `act`
runs:

```bash
pixi run test-local
```

Local scenarios are intended for fast feedback. They should avoid hosted-only
services unless `act` can emulate them reliably.

## Docs Workflow

The docs workflow generates reference pages, builds Sphinx output, and deploys
the resulting HTML to GitHub Pages. Source docs live under `docs/`, while
`docs/reference/` is ignored build output created before Sphinx runs.

## Release Workflow

The release workflow runs Release Please. Release behavior is driven by workflow
metadata and `.github/release-please` configuration.

## Adding New CI Coverage

Prefer adding scenario metadata to `devflow.yaml` over hand-writing one-off CI
jobs. The generated scenario workflow keeps test behavior discoverable from the
workflow metadata and reduces drift between workflows.
