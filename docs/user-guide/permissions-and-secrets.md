# Permissions And Secrets

Reusable workflows run inside the security context of the caller workflow. The
caller controls the event, token permissions, and available secrets. For the
catalog-wide trust model behind the guidance below — injection resistance, the
credential model, and artifact integrity — see {doc}`security-model`.

## Start With Read-Only Permissions

Most read, build, and test workflows should start with:

```yaml
permissions:
  contents: read
```

Add broader permissions only when the workflow needs them. Release and
publishing workflows may additionally need `packages`, `pages`, `id-token`, or
`contents: write`. Each workflow's requirement is documented on its reference
page.

## Grant the Full Caller-Permission Union

Because a reusable workflow declares its own per-job permissions, GitHub
validates the caller's granted permissions against the **union of the workflow's
top-level block and every job's block — at startup, before any `if:` condition
is evaluated**. The calling job must grant at least that union. A scope that
only a disabled optional job would use still counts, and under-granting fails
the whole run at startup, before any workflow code executes. For example, a
workflow with an embedded writeback commit job requires `contents: write` and
`actions: read` even for a read-only run, because the (possibly disabled) commit
job declares them.

Do not transcribe these unions from prose — read them from the source of truth.
Each workflow's exact required union is generated onto its reference page under
**Permissions**. Open the workflow's page in the
{doc}`workflow catalog </reference/catalog>` and grant that set verbatim — for
example {doc}`pypi-publish </reference/workflows/pypi-publish>`,
{doc}`anaconda-publish </reference/workflows/anaconda-publish>`, and
{doc}`zenodo-release </reference/workflows/zenodo-release>`.

## Pass Secrets Deliberately

Secrets are not available to a reusable workflow unless the caller passes them.
Two patterns are both legitimate; choose by workflow.

### Forward a scoped secret by name

For a narrowly scoped secret, forward it explicitly so only the named secret is
exposed:

```yaml
jobs:
  publish:
    # Pin to a real published tag or a commit SHA; no moving major tag
    # (anaconda-publish/v1) exists during the 0.x series.
    uses: QuanTizEd8/DevFlows/.github/workflows/anaconda-publish.yaml@anaconda-publish/vX.Y.Z
    with:
      publish-owner: my-org
    secrets:
      anaconda-token: ${{ secrets.ANACONDA_API_TOKEN }}
```

### Environment secrets with `secrets: inherit`

For the token-based publishing workflows (`anaconda-publish` and
`zenodo-release`), the **recommended** pattern is to store the token as a GitHub
**Environment secret** on the environment the credentialed job binds to (for
example `anaconda-release`, or the Zenodo environment you name) and let the
workflow read it with `secrets: inherit`:

```yaml
jobs:
  publish:
    uses: QuanTizEd8/DevFlows/.github/workflows/anaconda-publish.yaml@anaconda-publish/vX.Y.Z
    with:
      publish-owner: my-org
      promote-enabled: true
    secrets: inherit
```

`secrets: inherit` is not a blanket risk here: because the token lives on the
Environment, it is only available to the job that binds that Environment, and
the environment's required-reviewer and deployment-branch rules gate every real
publish. The workflow exposes the token as an environment variable on only the
single CLI step that uses it, and never forwards it to a third-party action.
Reserve caution for passing broad organization secrets to a workflow that does
not need them.

### OIDC instead of a token (`pypi-publish`)

`pypi-publish` takes **no PyPI token**. It publishes through
[PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) using an
OIDC token, so there is no publishing secret to forward at all. Grant
`id-token: write`, register the calling workflow as a trusted publisher on PyPI
or TestPyPI, and set `publish-environment-name` to match the environment named
in that trusted-publisher configuration. PEP 740 attestations are produced by
default. See {doc}`security-model` for the full credential model.

## Checkout Credentials

Workflows that check out code support token or SSH-key inputs and secrets. For
public read-only repositories the default `GITHUB_TOKEN` is usually enough. For
private dependencies or cross-repository checkout, use a narrowly scoped token
or deploy key rather than a broadly privileged one.

## Pull Request Events

Treat pull request workflows from forks as untrusted, and do not expose
publishing secrets to them. Use `publish-dry-run-enabled` for pull-request
checks: it runs the full credential-free verification path while skipping every
credentialed job at the job level, so no token or environment is ever exposed to
fork code. Be especially careful with `pull_request_target`, which runs with
privileges from the base repository.

## Pin the Workflow and Its Actions

DevFlows pins every third-party action it uses to a full commit SHA, managed by
Renovate, so you inherit that hardening automatically (see
{doc}`security-model`). On your side:

- Pin the DevFlows workflow reference to an exact release tag
  (`<workflow-id>/vX.Y.Z`) or a commit SHA. Every workflow is pre-1.0, so no
  moving major tag exists yet — see {doc}`versioning`.
- Pin any workflow-specific tools you select through inputs, especially Docker
  image tags (for example `pandoc-image`) and release tags, so a run is
  reproducible rather than tracking a floating upstream tag.
