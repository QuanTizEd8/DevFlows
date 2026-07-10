# Artifacts And Outputs

Reusable workflows can communicate with downstream jobs through outputs,
artifacts, or both.

## Workflow Outputs

Outputs are best for small strings such as generated identifiers, computed
paths, or status values. Read them through `needs.<job_id>.outputs` when a
workflow exposes outputs. Not every workflow exposes outputs; check the
generated reference page before depending on one.

## Artifacts

Artifacts are best for files and directories. Promoted workflows use
`artifact-download-*` inputs for artifact input and `artifact-upload-*` inputs
for artifact output.

A reusable workflow may upload files when artifact upload is enabled:

```yaml
with:
  artifact-upload-enabled: true
  artifact-upload-name: docs-html
  artifact-upload-path: output/site
  artifact-upload-if-no-files-found: error
```

A downstream job can download the artifact:

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

  inspect:
    runs-on: ubuntu-latest
    needs: convert
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: readme-html
          path: downloaded
      - run: test -f downloaded/readme.html
```

## Choosing Between Outputs And Artifacts

Use outputs for values that fit cleanly in workflow expressions. Use artifacts
for generated files, reports, archives, build products, and anything that needs
to be inspected by a later job.

## Artifact Input

When a workflow supports artifact download, enable it explicitly and name the
artifact or pattern to download:

```yaml
with:
  artifact-download-enabled: true
  artifact-download-name: prepared-sources
  artifact-download-path: input
```

The download runs before the workflow's main tool. Use this when one reusable
workflow consumes files produced by an earlier job.

## Commit Writeback

Some workflows can also commit selected generated files back to a branch. This
is opt-in and should only be used when repository state is the intended output.
DevFlows uses the {doc}`Writeback workflow <writeback>` as the shared commit
channel:

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

The caller must grant `contents: write` or pass a write-capable commit token.
Use artifact upload for reviewable CI outputs; use commit writeback when the
generated file should become part of the repository. Higher-level workflows
create a manifest-based writeback payload and delegate the final commit to
Writeback.

## Common Artifact Problems

- If an artifact path is relative, it is relative to the workspace used by the
  job running the reusable workflow.
- Set `artifact-upload-if-no-files-found: error` when missing output should fail
  CI.
- Be explicit about artifact names so downstream jobs can download the correct
  files.
- Local `act` runs are useful for conversion checks, but hosted GitHub runners
  are the reliable place to test artifact upload/download behavior.
