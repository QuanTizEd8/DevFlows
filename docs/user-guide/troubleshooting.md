# Troubleshooting

This page covers common problems when calling DevFlows workflows from another
repository.

## The Workflow Cannot Be Found

Check the `uses` path and tag:

```yaml
# Replace pandoc/v0.1.0 with the latest released tag; moving major tags
# (pandoc/v1) do not exist during the 0.x series.
uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v0.1.0
```

Reusable workflows must be published directly under `.github/workflows` in the
DevFlows repository. The tag must exist and must match the workflow versioning
scheme.

## Inputs Are Ignored Or Rejected

Input names are exact. Check the generated reference page for the workflow.
DevFlows does not promise aliases for unpublished draft interfaces.

## Artifacts Are Missing

Set missing artifacts to fail fast:

```yaml
with:
  artifact-upload-enabled: true
  artifact-upload-if-no-files-found: error
```

Then check whether the producing command writes files relative to the expected
working directory. If the workflow has a working-directory input, artifact paths
may still need to be expressed relative to the job workspace, depending on the
workflow's documented behavior.

## A Docker-Based Workflow Fails Locally But Works In CI

Local runners such as `act` approximate GitHub Actions. They can differ in
workspace mounts, service availability, and artifact behavior. Trust hosted
scenario tests for behavior that depends on GitHub services.

## Permissions Errors

Start by checking the caller workflow's top-level `permissions`. If a workflow
needs to write packages, pages, checks, or repository contents, the caller must
grant that permission explicitly.

GitHub validates nested reusable-workflow permissions **before the run starts**,
so the caller must grant at least the union every job in the called workflow
declares — even scopes only an optional, disabled job would use. In practice:

- Calling `pandoc` requires `contents: write` and `actions: read` (its embedded
  writeback commit job requires them) even for a read-only conversion.
- Calling `build-devcontainer` requires `packages: write`, `contents: read`, and
  `actions: read`.

A missing scope here fails the whole run at startup, before any job executes.

## Secret Or Checkout Failures

Check whether the workflow needs a token or SSH key for checkout. For private
repositories, cross-repository checkout, or submodules, the default GitHub token
may not be enough.
