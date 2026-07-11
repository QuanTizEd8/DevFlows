# Versioning And Updates

Each promoted DevFlows workflow has its own version line and release history.
The repository does not use one global version for all workflows.

## Project Status: Pre-1.0 (0.x)

DevFlows is pre-release: **no version tags are published yet**, and every
workflow is on a `0.x` version line (`release.major: 0`). While a workflow is
pre-1.0:

- Pin an **exact release tag** (`workflow-id/vX.Y.Z`) or a **commit SHA** once
  releases exist.
- **Moving major tags (`workflow-id/vN`) do not exist yet.** They begin at the
  workflow's `1.0.0` release.
- Interfaces may still change between `0.x` releases. Read the workflow
  changelog before updating.

## Tag Format

Workflow tags are scoped by workflow ID:

- Exact release: `workflow-id/vX.Y.Z` (the form every 0.x release uses)
- Moving major: `workflow-id/vN` (published from `1.0.0` onward)

Moving minor tags (`workflow-id/vX.Y`) are intentionally **not** published; pin
an exact patch release or a moving major tag instead. `vX.Y.Z` is a placeholder
for a real released version — substitute the actual tag once one exists.

## Which Reference Should You Use?

Pre-1.0, use an exact release tag for reproducible builds (replace `vX.Y.Z` with
a real released version):

```yaml
uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
```

Or a commit SHA for maximum supply-chain assurance:

```yaml
uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@0123456789abcdef0123456789abcdef01234567
```

Once a workflow reaches `1.0.0`, a moving major tag (for example `pandoc/v1`)
becomes available to track compatible updates within that major line. It does
not exist during the current pre-release `0.x` series.

## Compatibility Expectations

From `1.0.0` onward, maintainers avoid breaking existing callers within a major
version. Breaking interface changes require a new major version line.
Non-breaking additions, bug fixes, documentation changes, and security hardening
can happen within the same major line.

During `0.x`, the release tooling (release-please with `bump-minor-pre-major`)
maps **both breaking changes and new features to a minor bump** (for example
`0.2.0` to `0.3.0`) and reserves patch bumps for fixes. There is no
cross-release compatibility promise on a minor bump pre-1.0, so pin exact tags
or SHAs and review each update against the workflow changelog.

## Updating A Caller

When updating a caller repository:

1. Read the workflow changelog for the workflow you use.
2. Compare your current tag with the target tag.
3. Check whether new inputs or permissions are recommended.
4. Update the `uses` reference.
5. Run the caller repository's CI.

## Reproducibility Tips

Version the workflow and the tools it invokes. For example, the Pandoc workflow
lets you select a Pandoc Docker image. Prefer `pandoc/core:3.8` or
`pandoc/latex:3-ubuntu` style tags over `latest`.
