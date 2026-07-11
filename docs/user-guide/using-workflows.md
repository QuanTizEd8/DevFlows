# Calling Reusable Workflows

Reusable workflows are called at the job level with `jobs.<job_id>.uses`. They
are not called as a step. That means the reusable workflow owns the runner, job
steps, and job-level behavior for that call.

## Basic Call Shape

```yaml
name: Build documents

on:
  pull_request:
  push:
    branches:
      - main

permissions:
  # Pandoc's published form embeds a writeback commit job requiring these
  # scopes. GitHub validates nested permissions before the run starts, so the
  # caller must grant the union even for a read-only conversion.
  contents: write
  actions: read

jobs:
  pandoc:
    # DevFlows has no published tags yet; pin an exact pandoc/vX.Y.Z release
    # tag or a commit SHA. Moving major tags (pandoc/v1) begin at 1.0.
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=output/readme.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: readme-html
      artifact-upload-path: output/readme.html
```

Every workflow has its own generated reference page under the
{doc}`workflow catalog </reference/catalog>`. Use that page to find:

- supported inputs and defaults
- required and optional secrets
- outputs
- declared permissions
- examples
- test scenarios maintained by DevFlows

## Standard IO Channels

DevFlows workflows share a consistent shape for file movement, so a channel you
learn on one workflow behaves the same on the next:

- checkout inputs bring repository content into the workflow workspace
- `artifact-download-*` inputs bring previously produced files into the
  workspace before the main tool runs
- `artifact-upload-*` inputs publish generated files as workflow artifacts
- `commit-*` inputs optionally write selected generated files back to a
  repository branch (the shared writeback channel)

Two channels carry extra structure worth knowing before you chain workflows
together:

### The GitHub Pages Artifact Channel

Site builders publish through a GitHub Pages artifact rather than the generic
artifact channel. `docs-build` uploads the built site as a Pages artifact when
`pages-artifact-enabled: true` (no extra permissions) and exposes its name as
the `pages-artifact-name` output; `deploy-pages` then deploys that artifact by
name. The default artifact name on both is `github-pages` — also
`actions/deploy-pages`' expected default — so the chain works with zero extra
wiring. A plain `upload-artifact` artifact is **not** Pages-deployable; hand
`deploy-pages` a directory through its `artifact-download` channel plus
`pages-path` instead. The worked chain is in {doc}`getting-started-docs-pages`.

### The dist-manifest Integrity Contract

The Python tier adds an integrity contract on top of plain artifacts.
`python-build` emits, alongside its named artifacts, a `dist-manifest` output —
a schema-versioned JSON document listing every distribution file with its
`sha256` and `size` — and a `dist-sha256sums` output in the format
`slsa-github-generator` expects. Downstream publishers (`pypi-publish`,
`anaconda-publish`) take that manifest as an input and upload **only** files it
lists, byte-for-byte digest-matched, refusing anything unlisted or mismatched.
The verification runs in a credential-free job and again atomically inside the
credentialed publish job immediately before upload (a TOCTOU guard). See
{doc}`artifacts-and-outputs` for the contract and {doc}`getting-started-python`
for the worked chain.

Workflows may document additional channels when the underlying tool needs them,
but callers should expect these names to be consistent across the catalog.

(chaining-workflows)=

## Chaining Workflows

Reusable workflows chain through job outputs read as `needs.<job_id>.outputs.*`.
The producing job runs a DevFlows workflow, and the consuming job passes its
outputs into the next `with:` block. The Python tier is the richest example —
`python-build` exposes `dist-manifest`, `package-version`, and the per-flavor
artifact names:

```yaml
jobs:
  build:
    uses: QuanTizEd8/DevFlows/.github/workflows/python-build.yaml@python-build/vX.Y.Z
    permissions:
      contents: read
      actions: read

  publish:
    needs: build
    # Guard the chain: run only when the upstream flavor actually produced files.
    if: ${{ !cancelled() && needs.build.outputs.sdist-artifact-name != '' }}
    uses: QuanTizEd8/DevFlows/.github/workflows/pypi-publish.yaml@pypi-publish/vX.Y.Z
    permissions:
      contents: read
      actions: read
      id-token: write
    with:
      publish-index: pypi
      publish-dist-manifest: ${{ needs.build.outputs.dist-manifest }}
      publish-expected-version: ${{ needs.build.outputs.package-version }}
      artifact-download-enabled: true
      artifact-download-pattern: my-package-{sdist,wheels}
      artifact-download-merge-multiple: true
      artifact-download-path: dist
      publish-dist-path: dist
```

Two conventions make chains robust:

- **Guard on non-empty outputs.** An artifact-name or URL output is the empty
  string when its flavor produced nothing or its job was skipped. Guard the
  consuming job with
  `if: ${{ !cancelled() && needs.build.outputs.<name> != '' }}` so a broken or
  partial chain fails loudly instead of silently no-opping.
- **Pass the manifest and version through.** Feeding `dist-manifest` and
  `package-version` into the publisher makes tag/artifact skew impossible before
  an irreversible upload.

The container tier composes the same way:
{doc}`build-devcontainer </reference/workflows/build-devcontainer>` publishes an
image whose `devcontainer.metadata` label carries its features and lifecycle
hooks, and {doc}`devcontainer-run </reference/workflows/devcontainer-run>`
consumes that `image-ref` to run any command inside it **without rebuilding**
(the label supplies the features, hooks, `remoteUser`, and env automatically).
Build once, then run many commands — lint, tests, a script — against the same
prebuilt image.

## Publishing-Tier Patterns

The Publishing tier (`pypi-publish`, `anaconda-publish`, `zenodo-release`) and
the Pages deploy add three patterns worth understanding as a caller.

### Environment-Gated Publish Jobs

Every irreversible operation binds to a GitHub environment through a
`*-environment-name` input (`publish-environment-name`,
`zenodo-environment-name`, `pages-environment-name`, and the anaconda
`upload`/`promote`/`maintain` environments). Configure required reviewers and
deployment branch rules on that environment to gate the release — the reviewer
prompt and the deployment record belong to the environment, not the reusable
workflow. Bind separate environments to separate blast radii (staging
unreviewed, production with required reviewers).

### OIDC Trusted Publishing

`pypi-publish` and `deploy-pages` authenticate with a short-lived OIDC token
instead of a stored secret, so their publish jobs statically declare
`id-token: write`. Because GitHub validates nested job permissions at startup,
every calling job must grant `id-token: write` even for a dry-run.
`pypi-publish` takes no token secret at all (trusted publishing only, with PEP
740 attestations); `anaconda-publish` and `zenodo-release` have no OIDC option
and use token secrets instead. See {doc}`permissions-and-secrets`.

### Dry-Run Job Skip

Each publisher has a `publish-dry-run-enabled` (deploy-pages uses
`pages-deploy-enabled: false`) that skips the credentialed job **at the job
level**: the run still validates inputs, downloads artifacts, and
digest-verifies them, but no token is minted, no environment is bound, and no
required reviewer is pinged. This makes the whole ingestion-and-verification
path a safe pull-request check. The published-URL/DOI outputs are empty in
dry-run, so guard downstream consumers on a non-empty value.

## Inputs

Inputs are passed through the `with` block. Boolean and number inputs can be
written as native YAML values:

```yaml
with:
  checkout-fetch-depth: 0
  checkout-lfs: true
```

For long strings, prefer YAML block scalars. They make command-oriented inputs
easier to read and review:

```yaml
with:
  pandoc-arguments: >-
    --standalone --metadata=title:"Project Report" --output=dist/report.html
    docs/report.md
```

## Secrets

Reusable workflow secrets are passed with `secrets`. If a workflow supports a
custom checkout token or SSH key, pass only the secret needed for that caller:

```yaml
permissions:
  # Required by pandoc's nested writeback commit job; validated before the run.
  contents: write
  actions: read

jobs:
  pandoc:
    # Pin an exact pandoc/vX.Y.Z release tag or a commit SHA.
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
    secrets:
      checkout-token: ${{ secrets.DEVFLOWS_CHECKOUT_TOKEN }}
```

Do not pass broad repository or organization secrets to workflows that do not
need them. Keep secret names specific to their purpose.

## Outputs

Reusable workflow outputs are read from `needs.<job_id>.outputs` in downstream
jobs. Not every workflow exposes outputs. Check the generated reference page
before depending on one, and see [Chaining Workflows](#chaining-workflows) for
the guard-on-non-empty convention when you feed one workflow's outputs into the
next.

## Calling From Pull Requests

Be careful when a caller workflow runs on pull requests from forks. Avoid using
trusted secrets or privileged tokens with untrusted code. If a reusable workflow
checks out code, understand which repository and ref it checks out, and keep the
caller permissions as narrow as possible.

## Local Versus Hosted Behavior

GitHub-hosted runners are the source of truth. Local tools such as `act` are
useful for fast feedback, but they do not emulate every GitHub service. In
particular, artifact upload/download behavior can differ for newer action
versions. DevFlows keeps hosted scenario tests for paths that require GitHub
services.
