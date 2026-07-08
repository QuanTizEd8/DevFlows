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
    uses: owner/devflows/.github/workflows/pandoc.yaml@pandoc/v1
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=site/index.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: pandoc-html
      artifact-upload-path: site/index.html
```

Replace `owner/devflows` with the actual repository owner/name for the DevFlows
repository you use.

### The Short Version

1. Pick a workflow from the {doc}`workflow catalog </reference/catalog>`.
2. Read its generated reference page for inputs, secrets, outputs, permissions,
   examples, and test scenarios.
3. Call the workflow with a versioned reference:
   `owner/devflows/.github/workflows/<workflow-id>.yaml@<workflow-id>/v1`.
4. Prefer pinned input values, especially Docker image tags and release tags.
5. Give the caller workflow only the permissions and secrets it needs.
6. Use the standard IO channels when available: checkout for source input,
   artifact download for produced input, artifact upload for produced output,
   and opt-in commit writeback for repository updates.
7. Use exact tags or commit SHAs when reproducibility matters more than
   receiving compatible updates automatically.

### Recommended Version References

DevFlows uses per-workflow tags. For a workflow named `pandoc`, common
references look like this:

```yaml
# Stable convenience reference for compatible v1 updates.
uses: owner/devflows/.github/workflows/pandoc.yaml@pandoc/v1

# Exact workflow release.
uses: owner/devflows/.github/workflows/pandoc.yaml@pandoc/v1.2.3

# Highest assurance, pinned to a commit.
uses: owner/devflows/.github/workflows/pandoc.yaml@<commit-sha>
```

### What To Read Next

```{toctree}
:maxdepth: 2

using-workflows
versioning
permissions-and-secrets
artifacts-and-outputs
pandoc
writeback
troubleshooting
```
