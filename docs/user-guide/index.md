# User Guide

This guide is for people who call DevFlows reusable workflows from another
repository. DevFlows is a catalog of 14 reusable GitHub Actions workflows across
six categories, each versioned independently and published from
`.github/workflows`. The generated {doc}`workflow catalog </reference/catalog>`
is the authoritative source for every workflow's inputs, secrets, outputs,
permissions, examples, and test scenarios; this guide explains how to use them
together.

## The Catalog At A Glance

Browse the full, always-current listing in the
{doc}`workflow catalog </reference/catalog>`. The six categories:

- **Containers** —
  {doc}`devcontainer-build </reference/workflows/devcontainer-build>`,
  {doc}`binder-build </reference/workflows/binder-build>`
- **Documents** — {doc}`pandoc </reference/workflows/pandoc>`,
  {doc}`docs-build </reference/workflows/docs-build>`,
  {doc}`paper-openjournals </reference/workflows/paper-openjournals>`
- **Pages** — {doc}`deploy-pages </reference/workflows/deploy-pages>`
- **Python** — {doc}`python-build </reference/workflows/python-build>`,
  {doc}`python-test </reference/workflows/python-test>`,
  {doc}`python-lint </reference/workflows/python-lint>`
- **Publishing** — {doc}`pypi-publish </reference/workflows/pypi-publish>`,
  {doc}`anaconda-publish </reference/workflows/anaconda-publish>`,
  {doc}`zenodo-release </reference/workflows/zenodo-release>`
- **Utilities** — {doc}`writeback </reference/workflows/writeback>`

## Calling A Workflow

A consuming repository calls a workflow as a job with `jobs.<job_id>.uses`:

```yaml
jobs:
  convert-docs:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=site/index.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: pandoc-html
      artifact-upload-path: site/index.html
```

`QuanTizEd8/DevFlows` is the canonical repository (substitute your own fork if
you consume DevFlows from one). DevFlows is pre-release, so **no version tags
are published yet**: pin an exact `<workflow-id>/vX.Y.Z` release tag or a commit
SHA once releases exist, and replace `vX.Y.Z` with the real version. See
{doc}`versioning`.

## The Short Version

1. Pick a workflow from the {doc}`workflow catalog </reference/catalog>`.
2. Read its generated reference page for inputs, secrets, outputs, the exact
   caller-permission union, examples, and test scenarios.
3. Call it with a versioned reference:
   `QuanTizEd8/DevFlows/.github/workflows/<workflow-id>.yaml@<workflow-id>/vX.Y.Z`.
4. Grant the caller job the full permission union the reference page lists —
   GitHub validates nested permissions at startup, so a missing scope fails the
   run before any job executes. See {doc}`permissions-and-secrets`.
5. Prefer pinned input values, especially Docker image tags.
6. Use the standard IO channels — checkout for source, artifact download for
   produced input, artifact upload for produced output, and opt-in commit
   writeback for repository updates. See {doc}`artifacts-and-outputs`.

## What To Read Next

Start with a worked example for your use case (the getting-started pages), then
dig into the shared concepts.

```{toctree}
:maxdepth: 2

using-workflows
getting-started-python
getting-started-docs-pages
getting-started-research
versioning
permissions-and-secrets
security-model
artifacts-and-outputs
troubleshooting
```
