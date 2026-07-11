# Publishing-Tier Conventions

The three publishing workflows — `pypi-publish`, `anaconda-publish`, and
`zenodo-release` — perform irreversible, credentialed operations against
external registries. They share a deliberate set of safety conventions. This
page documents those conventions so a new publishing-tier workflow follows the
same pattern, and so a review of an existing one has a checklist. Each
convention is shown with the real source it comes from under
`workflows/<id>/workflow.yaml`.

## Credential Model

`pypi-publish` uses **OIDC trusted publishing only**. Its publish job declares
`permissions: id-token: write` and takes **no token secret**; PyPI mints a
short-lived token from the OIDC claim and the workflow attaches PEP 740
attestations. Never add a username/password or API-token input to it.

`anaconda-publish` and `zenodo-release` use **long-lived token secrets**
(`anaconda-token`; `zenodo-token` / `zenodo-sandbox-token`), each declared
`required: false` because dry-run and (for Zenodo) sandbox need none. A token is
exposed to exactly one step (below) and is expected to be stored as a **GitHub
environment secret** so the environment's protection rules gate access to it.

## Dry-Run With Job-Level Skip

Every publishing workflow exposes `publish-dry-run-enabled` (default `false`).
The credential-free jobs (validate, verify/prepare) always run; every mutating
job is skipped at the job level:

```yaml
publish:
  if: ${{ !inputs.publish-dry-run-enabled }}
  # ...
```

Because the skip is a job-level `if:`, a dry-run mints no OIDC token, creates no
deployment record, binds no environment, and pings no required reviewer — it
downloads the artifacts, digest-verifies them, and reports the plan. This is the
pull-request check and the credential-free scenario surface. Keep the verify /
plan computation in a separate job from the credentialed action so dry-run
exercises everything except the side effect.

## Environment Binding And Concurrency

Each credentialed job binds to a caller-named GitHub environment and takes a
serializing concurrency group:

```yaml
environment:
  name: ${{ inputs.upload-environment-name }}
concurrency:
  group: anaconda-publish-${{ inputs.upload-environment-name }}
  cancel-in-progress: false
```

The environment is where required reviewers and deployment branch rules live, so
binding the job to it is what makes a release gateable and auditable.
`cancel-in-progress: false` ensures an in-flight publish is never cancelled
mid-upload. Separate operations bind to separate environments so they can carry
different protection rules — `anaconda-publish` binds upload, promote, and
maintain to distinct environments (staging vs. release vs. maintain).

## Credential Isolation And Tokenless Preflight

A token is never granted to a whole job's worth of steps. It is exposed as an
env var on the **single** CLI step that needs it, and a preceding tokenless
preflight step fails fast with a clear message when the secret is absent — it
reads only a boolean presence expression, never the secret value:

```yaml
- name: Assert publishing credential present
  env:
    ANACONDA_TOKEN_PRESENT: ${{ secrets.anaconda-token != '' }}
    PUBLISH_DRY_RUN_ENABLED: ${{ inputs.publish-dry-run-enabled }}
  run: python "${DEVFLOWS_SCRIPT_ROOT}/anaconda-publish/preflight-token.py"

- name: Upload to anaconda.org
  env:
    ANACONDA_API_TOKEN: ${{ secrets.anaconda-token }} # only this step sees the token
    # ...domain env, all environment-mediated...
  run: python "${DEVFLOWS_SCRIPT_ROOT}/anaconda-publish/upload.py"
```

`zenodo-release` passes **both** the production and sandbox tokens to its single
deposit step and lets the script select and fail-closed, rather than using a
`sandbox && sandbox-token || token` expression that would silently inject the
production token into a sandbox run when the sandbox token is empty.

## No Checkout In Credentialed Jobs

The credentialed jobs do not check out the caller's repository. They run only
`setup-uv`, the preflight, an optional re-verify, and the single CLI step; the
DevFlows scripts arrive inlined by the materialize step, not by a checkout. So
no caller-controlled repository content executes in the job that holds the
token. Keep checkout (and any caller-file reading, such as a `CITATION.cff` or
release notes file) in the earlier credential-free jobs.

## TOCTOU Re-Verification

Between the verify job's artifact download and the credentialed job's own
download, an artifact could in principle be swapped. So immediately before the
credentialed step, a tokenless `reverify.py` re-hashes the files-to-upload
against the caller-supplied `publish-dist-manifest` — the same bidirectional
sha256/size check the verify job ran:

```yaml
- name: Re-verify distributions before upload
  env:
    PUBLISH_DIST_PATH: ${{ inputs.publish-dist-path }}
    PUBLISH_DIST_MANIFEST: ${{ inputs.publish-dist-manifest }}
    PUBLISH_EXPECTED_VERSION: ${{ inputs.publish-expected-version }}
  run: python "${DEVFLOWS_SCRIPT_ROOT}/anaconda-publish/reverify.py"
```

Only files listed in the manifest, byte-for-byte digest-matched, are ever
uploaded — that manifest is the integrity contract with the upstream builder
(`python-build`). `pypi-publish` achieves the same by re-running its
`verify-dist.py` inside the publish job before the upload step.

## Allowlisted, Environment-Mediated Arguments

Caller-supplied extra arguments are never interpolated into shell text. They are
passed through an environment variable, `shlex`-split by a DevFlows script, and
guarded by a strict allowlist:

- `anaconda-publish` `upload-arguments` accepts only cosmetic/metadata flags
  (`--no-progress`, `--no-register`, `--register`, `--keep-basename`,
  `--summary=…`, `--description=…`).
- `pypi-publish` `install-check-arguments` accepts only build-mode flags
  (`--no-binary`, `--only-binary`, `--no-deps`); index-selection flags, `-r`,
  and bare package names are rejected because the index and version are chosen
  by DevFlows.

Anything DevFlows owns (the index, the owner namespace, the target version) is
rejected, so a caller cannot redirect an upload or install through an argument.

## Type-The-Name Destructive Confirm

Irreversible operations require an arm switch whose value the caller must type
exactly, so a destructive run can never be triggered by a default:

- `anaconda-publish` `maintain-enabled` (channel removal) requires
  `maintain-confirm` to equal `publish-owner` exactly, and is mutually exclusive
  with upload/promote.
- `zenodo-release` `zenodo-publish-enabled` requires `zenodo-publish-confirm` to
  equal `release-tag` for a real (non-sandbox, non-dry-run) publish that
  permanently registers the DOI.

Validation rejects the run when the confirmation does not match. Pair every such
switch with dry-run so the destructive plan can be rehearsed credential-free.

## Independently-Gated Stages

Split a multi-stage release into separately-gated jobs rather than one
do-everything job. `anaconda-publish` stages to a `staging` label in the upload
job, then a separate `promote` job (its own environment and reviewers) relabels
to the final label; `maintain` is a third, isolated destructive job.
`zenodo-release` gates the GitHub release and the Zenodo deposit independently.
Each stage that can succeed or be skipped guards its downstream job with an
explicit `needs.<job>.result` check so a partial run never promotes.

## Author Checklist

When adding or reviewing a publishing-tier workflow:

- [ ] Credential model correct: OIDC (`id-token: write`, no token) **or** a
      `required: false` token secret — never both.
- [ ] `publish-dry-run-enabled` present; every mutating job skipped with
      `if: ${{ !inputs.publish-dry-run-enabled ... }}`.
- [ ] Each credentialed job binds a GitHub environment and a non-cancelling
      concurrency group.
- [ ] The token is exposed on exactly one step; a tokenless preflight precedes
      it and reads only a presence boolean.
- [ ] Credentialed jobs do not check out caller content.
- [ ] A re-verify against the caller manifest runs immediately before the
      irreversible step.
- [ ] Caller-supplied arguments are env-mediated, `shlex`-split, and
      allowlisted.
- [ ] Any irreversible operation has a type-the-name confirm and is
      dry-runnable.
- [ ] The caller permission union (including each job-level block) is documented
      in the workflow's `notes` and rendered in its reference page.
