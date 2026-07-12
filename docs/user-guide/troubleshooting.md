# Troubleshooting

This page covers common problems when calling DevFlows workflows from another
repository.

## The Workflow Cannot Be Found

Check the `uses` path and tag:

```yaml
# DevFlows has no published tags yet; pin an exact pandoc/vX.Y.Z release tag or a
# commit SHA. Moving major tags (pandoc/v1) begin at the 1.0 release.
uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
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

(permissions-errors)=

## Permissions Errors

Start by checking the caller workflow's top-level `permissions`. If a workflow
needs to write packages, pages, checks, or repository contents, the caller must
grant that permission explicitly.

GitHub validates nested reusable-workflow permissions **before the run starts**,
so the caller must grant at least the union every job in the called workflow
declares — even scopes only an optional, disabled job would use. In practice:

- Calling `pandoc` requires `contents: write` and `actions: read` (its embedded
  writeback commit job requires them) even for a read-only conversion.
- Calling `devcontainer-build` requires `packages: write`, `contents: read`, and
  `actions: read`.
- Calling `pypi-publish` requires `id-token: write` (OIDC trusted publishing),
  `contents: read`, and `actions: read` — all three even for a dry-run call.
- Calling `deploy-pages` requires `pages: write` and `id-token: write` plus
  `contents: read` and `actions: read`, even in deploy-only or package-only
  mode.
- Calling `zenodo-release` requires `contents: write`, `discussions: write`, and
  `actions: read`, even for a Zenodo-only call that skips the release job.

A missing scope here fails the whole run at startup, before any job executes.
The per-workflow union is listed in each generated reference page's Permissions
section. See {doc}`permissions-and-secrets` for the full model.

## Publishing Fails Partway Or Never Starts

The Publishing tier (`pypi-publish`, `anaconda-publish`, `zenodo-release`) and
`deploy-pages` add environment gating, OIDC, and digest verification. The common
failure modes:

### The Run Hangs "Waiting" Or The Reviewer Is Never Pinged

The publish job binds to a GitHub environment through its `*-environment-name`
input, but the environment does not exist or has no reviewers configured.

- Create the environment named by `publish-environment-name` /
  `zenodo-environment-name` / `pages-environment-name` (and the anaconda
  `upload`/`promote`/`maintain` environments) in repository settings.
- Configure the required reviewers and deployment branch rules **on the
  environment** — the reviewer prompt is an environment feature, not a workflow
  input. A run stuck "Waiting" needs a reviewer to approve the deployment.
- Store token secrets (`anaconda-token`, `zenodo-token`) as **environment
  secrets** on that environment so `secrets: inherit` resolves them.

### OIDC Trusted-Publisher Mismatch (PyPI)

`pypi-publish` uploads via OIDC trusted publishing only, so PyPI must have a
trusted publisher registered that matches the run. A mismatch fails the upload
with a claim-rejection error. Register the publisher on PyPI (and separately on
TestPyPI) for:

- your repository `owner/repo`,
- **your own calling workflow's filename** (PyPI validates the caller's
  top-level workflow, not the reusable workflow), and
- the environment name you pass as `publish-environment-name`.

`gh-action-pypi-publish` may print an "unsupported reusable workflow
configurations" warning; that is expected and publishing still works. TestPyPI
and PyPI need separate publisher registrations and separate environments.

### Startup Failure: The Caller Did Not Grant The Permission Union

GitHub validates every nested job's permissions **before the run starts**,
before any `if:` is evaluated, so the caller must grant the full documented
union even for scopes only a skipped or disabled job would use. A dry-run
`pypi-publish` call still needs `id-token: write`; a Zenodo-only
`zenodo-release` call still needs `contents: write` and `discussions: write`; a
package-only `deploy-pages` call still needs `pages: write` and
`id-token: write`. Grant the union from the generated reference page, or the
whole run fails at startup with a permissions error. See
[Permissions Errors](#permissions-errors).

### Digest-Mismatch Verification Failure

A manifest-verified publisher (`pypi-publish`, `anaconda-publish`, and
`zenodo-release` when a manifest is supplied) fails loudly, naming the file,
when a distribution does not match the `dist-manifest`: an unlisted file, a
wrong-kind file, a `sha256` or `size` mismatch, or a version that disagrees with
`publish-expected-version`. This is the integrity contract working as designed —
do not "fix" it by disabling verification. Usual causes:

- The `artifact-download-*` inputs pulled a different or extra artifact than the
  one the manifest describes; make sure `publish-dist-path` /
  `artifact-download-path` point at exactly the built distributions.
- `publish-dist-manifest` and the downloaded artifacts came from different runs;
  chain both from the same `python-build` job via `needs.build.outputs.*`.
- For `anaconda-publish`, `artifacts.conda-channel` in the manifest must equal
  `artifact-download-name`.

### Dry-Run Confusion: Empty Outputs, No Upload

With `publish-dry-run-enabled: true` (or `pages-deploy-enabled: false`), the
credentialed job is skipped at the job level: inputs are validated and artifacts
are digest-verified, but nothing is uploaded, no environment is bound, and no
token is minted. Consequences that look like bugs but are not:

- `published-url` / `pages-url` / `zenodo-doi` and other publish outputs are the
  **empty string** — guard downstream consumers on a non-empty value.
- No deployment record appears and no reviewer is pinged (nothing was deployed).
- `package-version` / `package-name` are still populated — they are what _would_
  have been published.

Turn dry-run off (and satisfy the environment gates) to publish for real.

## Secret Or Checkout Failures

Check whether the workflow needs a token or SSH key for checkout. For private
repositories, cross-repository checkout, or submodules, the default GitHub token
may not be enough.
