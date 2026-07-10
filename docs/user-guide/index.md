# User Guide

This guide is for people who want to call DevFlows reusable workflows from
another repository. The generated {doc}`workflow catalog </reference/catalog>`
remains the source for exact workflow interfaces.

## Quickstart

DevFlows publishes each promoted workflow from `.github/workflows` and versions
it independently. A consuming repository calls a workflow as a job:

```yaml
jobs:
  convert-docs:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v0.2.0
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=site/index.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: pandoc-html
      artifact-upload-path: site/index.html
```

`QuanTizEd8/DevFlows` is the canonical repository. Substitute your own fork's
owner/name if you consume DevFlows from a fork.

### The Short Version

1. Pick a workflow from the {doc}`workflow catalog </reference/catalog>`.
2. Read its generated reference page for inputs, secrets, outputs, permissions,
   examples, and test scenarios.
3. Call the workflow with a versioned reference. Every workflow is currently
   pre-1.0, so pin an exact release tag or a commit SHA:
   `QuanTizEd8/DevFlows/.github/workflows/<workflow-id>.yaml@<workflow-id>/vX.Y.Z`.
4. Prefer pinned input values, especially Docker image tags and release tags.
5. Give the caller workflow only the permissions and secrets it needs.
6. Use the standard IO channels when available: checkout for source input,
   artifact download for produced input, artifact upload for produced output,
   and opt-in commit writeback for repository updates.
7. Use exact tags or commit SHAs when reproducibility matters more than
   receiving compatible updates automatically.

### Recommended Version References

DevFlows uses per-workflow tags. Every workflow is currently pre-1.0 (`0.x`), so
pin an exact release tag or a commit SHA. Moving major tags become available
once a workflow reaches `1.0.0`. For a workflow named `pandoc`:

```yaml
# Exact workflow release (recommended during 0.x).
uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v0.2.0

# Highest assurance, pinned to a commit.
uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@<commit-sha>

# Available from the 1.0.0 release onward: moving major tag for compatible updates.
# uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v1
```

### What To Read Next

```{toctree}
:maxdepth: 2

using-workflows
versioning
permissions-and-secrets
artifacts-and-outputs
build-devcontainer
pandoc
writeback
troubleshooting
```
