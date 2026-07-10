# Permissions And Secrets

Reusable workflows run inside the security context of the caller workflow. The
caller controls the event, token permissions, and available secrets.

## Start With Read-Only Permissions

Most read/build/test workflows should start with:

```yaml
permissions:
  contents: read
```

Add broader permissions only when the workflow needs them. For example, release
or publishing workflows may need package, pages, id-token, or repository write
permissions. Those requirements should be documented on each workflow reference
page.

## Pass Secrets Deliberately

Secrets are not automatically available to reusable workflows unless the caller
passes them. Prefer explicit secrets:

```yaml
jobs:
  publish:
    uses: QuanTizEd8/DevFlows/.github/workflows/some-workflow.yaml@some-workflow/v1
    secrets:
      publish-token: ${{ secrets.PUBLISH_TOKEN }}
```

Avoid `secrets: inherit` unless the workflow has been reviewed for that use and
the caller repository intentionally exposes all inherited secrets to it.

## Checkout Credentials

Workflows that check out code often support token or SSH-key inputs/secrets. For
public read-only repositories, the default GitHub token is usually enough. For
private dependencies or cross-repository checkout, use a narrowly scoped token
or deploy key.

## Pull Request Events

Treat pull request workflows from forks as untrusted. Do not expose secrets to
untrusted code. Be especially careful with events such as `pull_request_target`,
which run with privileges from the base repository.

## Pinned Dependencies

DevFlows workflows should pin upstream actions in their own implementation.
Callers should still pin the DevFlows workflow reference to a tag or SHA and pin
any workflow-specific tools they select through inputs.
