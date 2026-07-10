# Using The Pandoc Workflow

The Pandoc workflow converts documents with official Pandoc Docker images. Its
generated reference page is {doc}`Pandoc </reference/workflows/pandoc>`.

## Minimal Example

```yaml
jobs:
  convert:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v1
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=output/readme.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: readme-html
      artifact-upload-path: output/readme.html
      artifact-upload-if-no-files-found: error
```

## Choosing An Image

Use a pinned image tag instead of `latest`.

- `pandoc/core` is appropriate for common conversions.
- `pandoc/latex` is appropriate for PDF or LaTeX output.
- `pandoc/extra` includes templates, filters, fonts, and extra tooling.

The default image is currently `pandoc/latex:3-ubuntu`.

## Arguments

`pandoc-arguments` is one string. It is parsed with shell-like quoting rules,
but it is not evaluated by a shell. Prefer YAML block scalars for long commands:

```yaml
with:
  pandoc-arguments: >-
    README.md --standalone --output=output/README.pdf
    --template=/.pandoc/templates/eisvogel.latex
```

Shell wildcard expansion does not happen inside `pandoc-arguments`. Pass
explicit filenames or generate file lists in a separate caller workflow job
before calling the reusable workflow.

## Working Directory

Use `pandoc-working-directory` to run Pandoc from a subdirectory:

```yaml
with:
  pandoc-working-directory: docs
  pandoc-arguments: >-
    --standalone --output=output/manual.html manual.md
```

The working directory must stay inside `GITHUB_WORKSPACE`.

## Artifact Download

Use artifact download when Pandoc should consume files produced by an earlier
job. The artifact is downloaded after checkout and before Pandoc runs:

```yaml
with:
  artifact-download-enabled: true
  artifact-download-name: prepared-markdown
  artifact-download-path: input
  pandoc-arguments: >-
    --standalone --output=output/readme.html input/README.md
```

For multiple artifacts, use `artifact-download-pattern` with
`artifact-download-merge-multiple: true`, or use `artifact-download-ids` when
you already have exact artifact IDs.

## Artifact Upload

Artifact upload is optional. If `artifact-upload-enabled` is false, the workflow
only runs Pandoc. If it is true, set `artifact-upload-path` to the file,
directory, or glob to publish:

```yaml
with:
  artifact-upload-enabled: true
  artifact-upload-name: pandoc-output
  artifact-upload-path: output/manual.html
  artifact-upload-if-no-files-found: error
```

## Commit Writeback

Commit writeback is also optional and disabled by default. Enable it only when
the converted file should be written back to a repository branch:

```yaml
permissions:
  contents: write

jobs:
  convert:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v1
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=docs/readme.html README.md
      commit-enabled: true
      commit-paths: docs/readme.html
      commit-message: "docs: update generated readme"
```

`commit-paths` is a newline-separated allowlist of files or directories to write
back. `commit-delete-paths` can declare removed generated files or directories.
The commit job delegates to the {doc}`Writeback workflow <writeback>` and is the
only job that asks for `contents: write`.

## The `pandoc/extra` Template Path Quirk

GitHub Actions rewrites `$HOME`, so bundled templates in `pandoc/extra` may need
explicit paths. For the Eisvogel template, use:

```yaml
with:
  pandoc-image: pandoc/extra:3.8
  pandoc-arguments: >-
    README.md --output=output/README.pdf --standalone
    --template=/.pandoc/templates/eisvogel.latex --listings
```
