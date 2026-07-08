# Versioning And Updates

Each promoted DevFlows workflow has its own version line and release history.
The repository does not use one global version for all workflows.

## Tag Format

Workflow tags are scoped by workflow ID:

- Exact release: `workflow-id/v1.2.3`
- Moving minor: `workflow-id/v1.2`
- Moving major: `workflow-id/v1`

For example, Pandoc consumers can reference:

```yaml
uses: owner/devflows/.github/workflows/pandoc.yaml@pandoc/v1
```

or:

```yaml
uses: owner/devflows/.github/workflows/pandoc.yaml@pandoc/v1.2.3
```

## Which Reference Should You Use?

Use a moving major tag when you want compatible updates:

```yaml
uses: owner/devflows/.github/workflows/pandoc.yaml@pandoc/v1
```

Use an exact release tag when reproducibility matters:

```yaml
uses: owner/devflows/.github/workflows/pandoc.yaml@pandoc/v1.2.3
```

Use a commit SHA when you need maximum supply-chain assurance:

```yaml
uses: owner/devflows/.github/workflows/pandoc.yaml@0123456789abcdef0123456789abcdef01234567
```

## Compatibility Expectations

Within a major version, maintainers should avoid breaking existing callers.
Breaking interface changes require a new major version line. Non-breaking
additions, bug fixes, documentation changes, and security hardening can happen
within the same major line.

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
