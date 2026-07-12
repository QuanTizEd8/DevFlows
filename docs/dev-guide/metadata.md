# Workflow Metadata

Each promoted workflow has a `devflow.yaml` metadata file. The metadata file is
used by validation, generated docs, generated scenario tests, and release
configuration checks.

## Required Identity Fields

```yaml
id: pandoc
name: Pandoc
summary:
  Convert documents with official Pandoc Docker images, with uniform checkout,
  artifact, and optional writeback channels.
status: active
owners:
  - DevFlows maintainers
```

The `id` must match the workflow directory name. Supported statuses are
`active`, `deprecated`, and `experimental`.

## Release Configuration

```yaml
release:
  type: simple
  major: 0
```

The release type must match the corresponding release-please package config.
`release.major` records the workflow's current released major version line — an
integer, `0` while the catalog is pre-1.0 (every workflow ships `major: 0`
today). It drives the version line shown in generated docs, and
`task release-check` cross-validates that it equals the major component of the
workflow's release-please manifest version, so the two cannot silently diverge.
See {doc}`release` for the 0.x contract and the deliberate 1.0 promotion.

## Docs Metadata

```yaml
docs:
  category: Documents
  keywords:
    - pandoc
    - documents
    - conversion
```

Use notes for important behavior that is not obvious from the workflow syntax:

```yaml
notes:
  - Use pinned Pandoc image tags instead of latest for reproducible conversions.
```

## Shared IO Channels

Domain workflows should not hand-author the common checkout, artifact, or
patch-emit interface. Declare the channels the workflow supports in
`devflow.yaml`, and `devflows sync` will add the corresponding public inputs,
secrets, steps, and permissions to `.github/workflows/<id>.yaml`.

```yaml
io:
  job: pandoc
  runtime: true
  checkout: true
  artifact-download: true
  artifact-upload: true
  patch-emit: true
```

`job` names the runner job that should receive the generated steps. `runtime`
injects the "Materialize DevFlows runtime scripts" step (id `devflows-runtime`),
which at run time inlines every `${DEVFLOWS_SCRIPT_ROOT}/...` script the job
references into `$RUNNER_TEMP/devflows` — there is no runtime checkout of the
DevFlows repository. List any additional job that also runs those scripts under
`runtime-jobs` so it gets its own materialize step. `patch-emit` requires
`checkout` (a git workspace): it appends two suffix steps that capture the job's
workspace changes as a single patch artifact (`changes.patch`) with plain
`git diff`, forcing **no** `contents: write` on callers. Committing that patch
is a separate composition — a job that calls the `writeback` workflow (the sole
holder of `contents: write`) with the same `patch-artifact-name` to apply and
push it.

A workflow whose jobs each need a channel beyond the single `job` lists those
jobs under `checkout-jobs` or `artifact-download-jobs` (mirroring
`runtime-jobs`). The generator injects the same pinned checkout /
artifact-download step into each listed job, ahead of that job's own steps and
in the same order as `job`, and grants the job the permission the channel needs
(`contents: read` for checkout, `actions: read` for artifact-download). A matrix
build whose legs all need the checked-out source is the motivating case. None of
the listed jobs may repeat `job`, and the corresponding channel (`checkout` or
`artifact-download`) must be enabled.

```yaml
io:
  job: dist
  runtime: true
  checkout: true
  artifact-download: true
  checkout-jobs:
    - cibw
    - conda
  artifact-download-jobs:
    - conda
  runtime-jobs:
    - cibw
    - conda
```

## Examples

Examples are checked-in caller workflows:

```yaml
examples:
  - name: Markdown to HTML
    path: tests/fixtures/pandoc/markdown-to-html.yaml
```

Generated workflow reference pages render these example files inline. Keep
examples realistic and small enough to read.

## Test Scenarios

Scenarios define executable workflow tests:

```yaml
tests:
  scenarios:
    - id: markdown-html-local
      name: Markdown to HTML without artifact upload
      runs:
        - local
      cleanup:
        - .devflows-test/pandoc/markdown-html-local
      inputs:
        checkout-enabled: false
        pandoc-image: pandoc/core:3.8
        pandoc-arguments: >-
          --standalone
          --output=.devflows-test/pandoc/markdown-html-local/example.html
          README.md
      assertions:
        - type: file-exists
          path: .devflows-test/pandoc/markdown-html-local/example.html
```

See [Testing](testing.md) for supported scenario fields and assertion types.
