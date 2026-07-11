# Security Model

DevFlows is a catalog of reusable GitHub Actions workflows that other
repositories call. Because a reusable workflow runs inside the caller's security
context, the hardening in these workflows is a first-class feature, not an
afterthought. This page explains the security model a consumer can rely on and
the responsibilities that stay on the caller's side.

For how to report a vulnerability and what is in scope, see the repository
[Security Policy](https://github.com/QuanTizEd8/DevFlows/blob/main/SECURITY.md).
For the day-to-day mechanics of granting permissions and passing secrets, see
{doc}`permissions-and-secrets`.

## You Are the Security Boundary

Every DevFlows workflow treats **caller-supplied inputs and secrets as
untrusted**. A workflow cannot know whether a value came from a trusted
maintainer or from an attacker-controlled pull request, so it never trusts the
value's content.

- **Environment-variable mediation, never shell interpolation.** Caller values
  reach a step as environment variables declared in that step's `env:` block
  (for example `PUBLISH_INDEX: ${{ inputs.publish-index }}`). The `run:` body
  then invokes a Python script that reads those variables from the environment.
  No `${{ inputs.* }}` or `${{ secrets.* }}` expression is ever interpolated
  directly into a `run:` shell body, so a malicious input cannot break out of a
  string and become a command. This closes the classic Actions script-injection
  hole.
- **`shlex`-split arguments behind strict allowlists.** Where a workflow accepts
  free-form tool arguments (for example `pandoc-arguments`,
  `install-check-arguments`, `upload-arguments`, `repo2docker-arguments`), the
  string is parsed with Python's `shlex.split` and then checked against an
  allowlist of permitted flags. Flags that DevFlows owns or that would redirect
  behavior are rejected: `pypi-publish` accepts only `--no-binary`,
  `--only-binary`, and `--no-deps` and rejects any index-selection flag;
  `anaconda-publish` accepts only cosmetic metadata flags; `binder-build`
  rejects the flags its typed inputs already own. An argument input can never
  smuggle in a new index URL, an alternate credential, or a bare package name.
- **Structured validation before any side effect.** Paths are checked to stay
  inside the workspace (no absolute paths, no `..`), version and label strings
  are charset-validated, and destructive actions require a type-the-name arm
  switch (for example `zenodo-publish-confirm` must equal the release tag and
  `maintain-confirm` must equal the owner name). Validation runs in a
  credential-free `validate` job before any job that holds a token.

The caller still owns the decisions DevFlows cannot make for you: which
repository and ref you check out, which secrets you pass, and how you gate
workflows on pull requests from forks. Treat fork pull requests as untrusted and
do not expose publishing secrets to them.

## SHA-Pinned Actions and Inlined Scripts

DevFlows minimizes the third-party code that runs in your context and keeps
every external dependency auditable.

- **Every third-party action is pinned to a full commit SHA**, with a trailing
  `# vX.Y.Z` comment restoring the human-readable version the bare SHA hides
  (for example
  `uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b # v1.14.0`).
  A single registry, `src/devflows/actions.py` (`ACTION_PINS`), is the source of
  truth for every pin. The generator (the _adapter model_) maps DevFlows inputs
  onto each pinned action's real interface, and an adapter contract test asserts
  the emitted `with:` keys still match when a pin is bumped, so an upstream
  interface change cannot silently break a workflow.
- **Renovate keeps the pins current.** `renovate.json5` enforces the
  digest-pin-with-version-comment policy, bumps the `ACTION_PINS` registry
  through a custom manager, and updates the ephemerally installed tool pins
  (`jupyter-repo2docker`, `anaconda-client`, the `openjournals/inara` image,
  `pyyaml`, `requests`) in place. Upgrades arrive as reviewable pull requests
  rather than floating tags that move under you.
- **Runtime scripts are inlined at publish time, not checked out at run time.**
  Each workflow's Python helper scripts are embedded into the generated workflow
  YAML and materialized to a temporary directory during the run. A consumer that
  calls a DevFlows workflow never triggers a runtime checkout of DevFlows (or
  any other) source, so there is no window in which third-party code could be
  swapped in between pin and execution. Inlined scripts are required to be
  **ASCII-only**; a non-ASCII byte fails generation, because it would otherwise
  make GitHub silently reject the workflow at startup.
- **A hard 115,000-byte cap on every generated workflow.** GitHub rejects an
  oversized workflow file at startup with an opaque error that no linter can
  see. DevFlows enforces `MAX_GENERATED_WORKFLOW_BYTES = 115000` at generation
  time so a size regression fails locally and loudly instead of surfacing only
  on a hosted run. This is a robustness measure that keeps the published catalog
  runnable.

## Least Privilege and the Caller-Permission Union

Every workflow declares `permissions: {}` at the top level and grants each job
only the scopes it needs. A credential-free `validate` or `verify` job holds no
write permission; a job that mints an OIDC token or writes a release holds
exactly that scope and nothing more.

There is one rule every caller must understand:

```{important}
GitHub validates a reusable-workflow call's granted permissions against the
**union of every job's permission block** in the called workflow — its top-level
block plus each job's block — **at startup, before any `if:` condition is
evaluated**. A scope that only a disabled optional job would use still counts. If
the calling job does not grant at least the full documented union, the entire run
fails at startup, before any DevFlows code runs.
```

So you must grant the union, not just the scopes your particular configuration
exercises. For example, calling `pypi-publish` in dry-run mode still requires
`id-token: write`, because the (skipped) publish job declares it; calling
`zenodo-release` for a GitHub-release-only run still requires the
`discussions: write` its release job can use.

Do not memorize these unions from prose. Each workflow's exact, single-sourced
union is generated onto its reference page under **Permissions** — for example
{doc}`pypi-publish </reference/workflows/pypi-publish>`,
{doc}`anaconda-publish </reference/workflows/anaconda-publish>`,
{doc}`zenodo-release </reference/workflows/zenodo-release>`, and
{doc}`binder-build </reference/workflows/binder-build>` — all reachable from the
{doc}`workflow catalog </reference/catalog>`. Grant that union verbatim.

## Credential Model

The publishing tier is deliberately split by credential type.

### PyPI: OIDC trusted publishing only

`pypi-publish` **takes no PyPI token**. It uploads through
[PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/): the
publish job requests an OIDC token (`id-token: write`) and hands it to
`pypa/gh-action-pypi-publish`, which exchanges it for a short-lived,
audience-scoped upload credential. There is no long-lived secret to leak,
rotate, or forward. The workflow rejects arbitrary repository URLs for
`publish-index` (only `pypi` and `testpypi` are accepted) precisely because any
other target would imply an unsupported token flow. PEP 740 digital attestations
are generated and uploaded by default (`attestation-enabled`), binding each
distribution to the workflow that built it.

### anaconda.org and Zenodo: isolated token secrets

`anaconda-publish` and `zenodo-release` need long-lived API tokens, so they
treat them with matching care:

- The token is passed as a secret (`anaconda-token`; `zenodo-token` /
  `zenodo-sandbox-token`) and exposed as an environment variable
  (`ANACONDA_API_TOKEN`, `ZENODO_TOKEN`) **only on the single DevFlows-owned CLI
  step that must use it** — never at the workflow or job level, and **never
  forwarded to a third-party action**. `zenodo-release` passes both the
  production and sandbox tokens to its deposit script and lets the script select
  and fail closed, so a sandbox run can never accidentally spend the production
  token.
- Each credentialed job **binds to a GitHub Environment** (for example
  `anaconda-staging`, `anaconda-release`, and a Zenodo environment you name).
  Configure required reviewers and deployment-branch rules on those environments
  to gate every real publish behind human approval. A preflight step asserts the
  token is actually present before the workflow attempts an upload, so a
  misconfigured environment fails early instead of half-publishing.

For these two workflows, storing the token as an **environment secret** and
calling with `secrets: inherit` is the recommended pattern — see
{doc}`permissions-and-secrets`.

### Dry-run skips the credentialed jobs entirely

Every publishing workflow (and `binder-build`) supports
`publish-dry-run-enabled`. When true, the credentialed jobs are skipped at the
**job level** via `if: ${{ !inputs.publish-dry-run-enabled }}`. A skipped job
never binds its Environment, never requests an OIDC token, never reads a secret,
and never pings a required reviewer. Dry-run runs the full verification path
(download, digest-verify, plan) with no credential, which makes it the safe
default for pull-request checks.

## Integrity: Verify, Re-Verify, Attest

DevFlows treats publishing as irreversible and guards the bytes end to end.

- **Digest-verified distribution manifests.** `python-build` emits a schema-1
  `dist-manifest` (each file carries its `sha256`, `size`, and `kind`). The
  publishing workflows upload **only** files listed in that manifest, verified
  byte-for-byte, and an optional `publish-expected-version` guard makes
  tag/artifact skew impossible. Chain the manifest through
  `needs.build.outputs.dist-manifest` — see {doc}`artifacts-and-outputs`.
- **TOCTOU re-verification before the irreversible step.** The manifest is
  verified once in the credential-free `verify` job and then **re-verified
  inside the credentialed publish job**, immediately before the upload. An
  artifact that was altered between download and publish is caught at the last
  possible moment, before anything leaves your runner.
- **Writeback is a validated, digest-checked channel.** The optional commit
  writeback captures selected files into a manifest of per-file SHA-256 digests,
  then a separate `writeback` job re-verifies every file's digest before writing
  it. It refuses symlinks (both as a source and as a write target), refuses to
  traverse a symlinked parent directory, rejects `..` and absolute paths, and
  never touches `.git`. An optional `commit-expected-base-sha` acts as a
  compare-and-swap so a writeback cannot land on a branch that moved underneath
  it.
- **Build provenance attestation.** `binder-build` attaches an
  `actions/attest-build-provenance` SLSA attestation to the pushed image's
  manifest digest and can emit a one-line reproducibility Dockerfile pinning
  that exact `sha256` digest, so downstream consumers can verify what was built.

## Supply Chain and How to Pin

Pulling the model together, the supply chain a consumer inherits is: SHA-pinned,
Renovate-managed third-party actions; inlined ASCII-only scripts with no runtime
third-party checkout; least-privilege per-job permissions; OIDC trusted
publishing for PyPI and environment-gated, single-step-isolated token secrets
for anaconda.org and Zenodo; digest-verified, re-verified artifacts; and
provenance attestation for images.

Your part is to **pin the DevFlows workflow reference itself**. The repository
is pre-1.0 and publishes per-workflow tags, so pin an exact release tag or a
commit SHA:

```yaml
jobs:
  publish:
    # Exact release tag (recommended during 0.x). Replace vX.Y.Z with a real
    # published tag; no moving major tag (pypi-publish/v1) exists before 1.0.
    uses: QuanTizEd8/DevFlows/.github/workflows/pypi-publish.yaml@pypi-publish/vX.Y.Z

    # Highest assurance: pin to a commit SHA.
    # uses: QuanTizEd8/DevFlows/.github/workflows/pypi-publish.yaml@<commit-sha>
```

Also pin the tool versions you pass as inputs — Docker image tags,
`pandoc-image`, and similar — so a run is reproducible rather than tracking a
floating upstream tag. See {doc}`versioning` for the full tag mechanics.
