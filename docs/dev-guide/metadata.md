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
  major: 1
```

The release type must match the corresponding release-please package config. The
major version is used in generated docs to show the current version line.

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
writeback interface. Declare the channels the workflow supports in
`devflow.yaml`, and `devflows sync` will add the corresponding public inputs,
secrets, steps, permissions, and commit job to `.github/workflows/<id>.yaml`.

```yaml
io:
  job: pandoc
  runtime: true
  checkout: true
  artifact-download: true
  artifact-upload: true
  writeback: true
```

`job` names the runner job that should receive the generated steps. `runtime`
adds the DevFlows runtime checkout needed by workflows that execute support
scripts published under `.github/workflows/<workflow-id>/`. `writeback` requires
`runtime` because generated workflows create the writeback payload with the
shared writeback script.

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
