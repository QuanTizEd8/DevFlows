# Continuous Integration

DevFlows CI protects both the project tooling and the reusable workflows.

## Main CI Workflow

`.github/workflows/devflows-ci.yaml` has two jobs, both running inside the
devcontainer.

**`Validate`** runs the full lint/test suite:

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

**`Adapter contract`** runs the network-backed adapter contract test, but only
when a pull request actually touches an action pin or a workflow that consumes
one. A guard step diffs the PR against its base for changes to
`src/devflows/actions.py`, any `workflows/*/workflow.yaml`, or any
`.github/workflows/*.yaml`; when none matched, the job completes without running
the test. When they did, it runs:

```bash
task test-contract   # pixi run -- pytest -m network tests/test_contract.py
```

which fetches each pinned action's `action.yml` at its pinned SHA and asserts
that every `with:` key the generator emits still exists — so a pin bump that
renames or drops an action input is caught before it ships. The test is marked
`network` and excluded from `task test`, which is why it runs in this dedicated
job. Because the job always completes (running the test or skipping it), it is
safe to require as a branch-protection status check. See
{doc}`adapter-and-action-pins` for the pin registry and how the contract is
enforced.

## Hosted Scenario Workflows

One `.github/workflows/devflows-scenarios-<id>.yaml` file per catalog workflow
is generated from workflow metadata. Each calls its promoted reusable workflow
and then runs assertion jobs. The suite is partitioned per owning workflow so no
single file crosses the `MAX_GENERATED_WORKFLOW_BYTES = 115_000` byte cap that
GitHub startup-rejects; every file shares the same `pull_request` / `push`
trigger, so GitHub runs them all in parallel on one event and total coverage is
unchanged. Hosted scenario tests are the right place to verify behavior that
needs real GitHub services.

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

`.github/workflows/devflows-docs.yaml` has a `Build` job and a `Deploy` job.
`Build` runs `task docs` in the devcontainer (which generates reference pages,
then builds Sphinx HTML). Pull requests build the docs to catch Sphinx errors
but stop there; only pushes to `main` (and manual dispatch) reach `Deploy`.
Source docs live under `docs/`, while `docs/reference/` is ignored build output
created before Sphinx runs.

`Deploy` dogfoods the catalog: rather than hand-rolling configure/upload/deploy,
it downloads the built site artifact and **calls the repository's own
`deploy-pages` reusable workflow** to package and publish it to GitHub Pages
(the same pattern as `devflows-devcontainer.yaml` calling `devcontainer-build`).
Because that is a nested reusable-workflow call, the `Deploy` job grants the
full permission union `deploy-pages` requires (`pages: write`,
`id-token: write`, `contents: read`, `actions: read`) — GitHub validates that at
startup. A concurrency group lets a `main` deploy finish without being cancelled
by a newer PR build.

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
the repository's own `devcontainer-build` reusable workflow to prebuild and
publish the CI/development devcontainer image plus a registry build cache to
GHCR. It runs on `.devcontainer/**` changes on `main`, weekly, and on demand;
`devflows-ci.yaml` and `devflows-docs.yaml` reuse the cache.

## Adding New CI Coverage

Prefer adding scenario metadata to `devflow.yaml` over hand-writing one-off CI
jobs. The generated scenario workflow keeps test behavior discoverable from the
workflow metadata and reduces drift between workflows.
