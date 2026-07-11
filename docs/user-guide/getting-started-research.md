# Getting Started: Research Software Releases

This page covers the research-software workflows: `zenodo-release` cuts a GitHub
Release and mints a Zenodo DOI from a tag, and `paper-openjournals` builds a
JOSS, JOSE, or ReScience C paper. It also shows the `python-build` →
`zenodo-release` asset chain that attaches your built distributions to the
release and archives them under a DOI. The generated reference pages are the
authoritative source for every input, secret, output, and the caller-permission
union:

- {doc}`Zenodo Release </reference/workflows/zenodo-release>`
- {doc}`Open Journals Paper Build </reference/workflows/paper-openjournals>`

Replace every `vX.Y.Z` with a real released tag; DevFlows has no published tags
yet (see {doc}`versioning`).

## Zenodo Release: Two Independently-Gated Targets

`zenodo-release` has two targets that are separate booleans — a GitHub Release
(`release-enabled`, default on) and a Zenodo deposition (`zenodo-enabled`,
default off) — and at least one must be true. A consumer can cut a GitHub
Release only (no Zenodo account), a Zenodo deposition only, or both. When both
run, the minted or reserved DOI is appended to the release notes.

No third-party action ever holds a secret: the GitHub Release is driven by the
`gh` CLI with the built-in `GITHUB_TOKEN`, and Zenodo by a DevFlows-owned script
that calls the Zenodo REST API directly. The token reaches exactly one deposit
step, and that credentialed job disables checkout so caller code never coexists
with the token.

Callers grant the union `zenodo-release` declares across its jobs:
`contents: write` (creates the Release), `actions: read` (the artifact-download
channel that ingests assets), and `discussions: write` (requested by the release
job; only exercised when `release-discussion-category` is set, but validated at
startup regardless). All authority to mutate Zenodo comes from the token secret,
not a `GITHUB_TOKEN` scope. See {doc}`permissions-and-secrets`.

### Three-Tier Irreversibility

Zenodo publishing is honest by construction, in three tiers:

1. **dry-run** (`publish-dry-run-enabled: true`) — `prepare` previews the whole
   plan; both credentialed jobs are skipped at the job level, no environment is
   bound, no token is minted.
2. **draft** (default) — creates or updates the deposition and reserves a DOI on
   the real or sandbox server; fully discardable.
3. **publish** (`zenodo-publish-enabled: true`) — IRREVERSIBLE. A published
   Zenodo record cannot be deleted, so a real (non-sandbox, non-dry-run) publish
   additionally requires `zenodo-publish-confirm` to equal `release-tag` exactly
   (a type-the-name guard) and a protected `zenodo-environment-name`.

Rehearse first against **Zenodo Sandbox** (`zenodo-sandbox-enabled: true`),
which issues discardable `10.5072` DOIs from `sandbox.zenodo.org` using
`zenodo-sandbox-token`. Keep the sandbox and production tokens as separate
secrets so a rehearsal never risks the production credential.

### The python-build to zenodo-release Asset Chain

Build the distributions with `python-build`, then archive them under a DOI. The
release job runs only when the upstream build produced an sdist, and
`publish-dist-manifest` lets `zenodo-release` sha256- and size-verify the assets
before upload. Store `zenodo-token` (and `zenodo-sandbox-token`) as environment
secrets on the bound `zenodo-environment-name` and pass them with
`secrets: inherit`:

```yaml
name: Release to GitHub and Zenodo from a tag

on:
  push:
    tags: ["v*"]

permissions: {}

jobs:
  build:
    name: Build distributions
    permissions:
      contents: read
      actions: read
    uses: QuanTizEd8/DevFlows/.github/workflows/python-build.yaml@python-build/vX.Y.Z
    with:
      dist-artifact-prefix: myproject

  release:
    name: Cut the GitHub + Zenodo release
    needs: build
    # Chaining convention: run only when the upstream distributions exist.
    if: ${{ !cancelled() && needs.build.outputs.sdist-artifact-name != '' }}
    permissions:
      contents: write
      discussions: write
      actions: read
    uses: QuanTizEd8/DevFlows/.github/workflows/zenodo-release.yaml@zenodo-release/vX.Y.Z
    secrets: inherit
    with:
      release-tag: ${{ github.ref_name }}
      release-enabled: true
      release-asset-globs: |
        *.tar.gz
        *.whl
      zenodo-enabled: true
      # Bind an UNPROTECTED environment for sandbox, a PROTECTED one for real Zenodo.
      zenodo-environment-name: zenodo
      # Pre-fill metadata from CITATION.cff; explicit zenodo-* inputs override it.
      zenodo-metadata-cff-path: CITATION.cff
      zenodo-asset-globs: |
        *.tar.gz
        *.whl
      # Verify every uploaded asset against the build's integrity manifest.
      publish-dist-manifest: ${{ needs.build.outputs.dist-manifest }}
      artifact-download-enabled: true
      artifact-download-pattern: myproject-{sdist,wheels}
      artifact-download-merge-multiple: true
      artifact-download-path: dist
```

This leaves a discardable **draft** deposition with a reserved DOI. To register
the DOI permanently, add `zenodo-publish-enabled: true` and
`zenodo-publish-confirm: ${{ github.ref_name }}` and bind a protected
environment with required reviewers. Deposition metadata comes from typed
`zenodo-*` inputs or `CITATION.cff` (explicit inputs always winning); the
{doc}`Zenodo Release reference </reference/workflows/zenodo-release>` documents
the metadata fields, the concept-versus-version DOI split, and the new-version
flow.

### GitHub Release Only

Drop the Zenodo inputs for a plain release. The permission union is unchanged —
GitHub validates the release job's `contents: write` and `discussions: write` at
startup even when Zenodo is off:

```yaml
release:
  needs: build
  if: ${{ !cancelled() && needs.build.outputs.sdist-artifact-name != '' }}
  permissions:
    contents: write
    discussions: write
    actions: read
  uses: QuanTizEd8/DevFlows/.github/workflows/zenodo-release.yaml@zenodo-release/vX.Y.Z
  with:
    release-tag: ${{ github.ref_name }}
    release-enabled: true
    zenodo-enabled: false
    release-asset-globs: "*.tar.gz"
    release-generate-notes-enabled: true
    artifact-download-enabled: true
    artifact-download-name: ${{ needs.build.outputs.sdist-artifact-name }}
    artifact-download-path: dist
```

## Open Journals Paper Build

`paper-openjournals` builds a JOSS, JOSE, or ReScience C paper from a Markdown
source with the pinned `openjournals/inara` container and collects the requested
flavors (draft or final PDF, JATS, Crossref XML, CFF, HTML, LaTeX, ...) into one
artifact. It is a pure document build with no external side effects: no dry-run
switch, no environment gating, no credentials. Callers grant only
`contents: read` (to check out the paper source) and `actions: read` (the
artifact channel).

```yaml
name: Build the JOSS paper

on:
  workflow_dispatch:

permissions:
  contents: read
  actions: read

jobs:
  build-paper:
    uses: QuanTizEd8/DevFlows/.github/workflows/paper-openjournals.yaml@paper-openjournals/vX.Y.Z
    with:
      paper-journal: joss
      paper-source-path: docs/paper.md
      paper-flavors: |
        draft-pdf
        jats
      artifact-upload-enabled: true
      artifact-upload-name: joss-paper
      artifact-upload-path: paper-build
      artifact-upload-if-no-files-found: error
```

`paper-journal` and `paper-source-path` are required. `paper-flavors` is a
newline-separated list from a fixed vocabulary; each flavor is collected into
its own subdirectory under `paper-output-directory`, and the whole tree uploads
as one artifact when you point `artifact-upload-path` at it. The heavy PDF
flavors compile LaTeX and are slow — rehearse a single flavor against a fixture
paper (the build has no side effects, so it is always safe to run). The
{doc}`Open Journals reference </reference/workflows/paper-openjournals>` lists
the full flavor vocabulary and the CFF example.

### Archiving a Paper Under a DOI

`zenodo-release`'s digest manifest is optional precisely because assets are
heterogeneous — a built distribution has a `dist-manifest`, a paper PDF does
not. To archive a paper, build it with `paper-openjournals`, upload the PDF as
an artifact, then feed it to `zenodo-release` through the artifact-download
channel with `zenodo-asset-globs` and no `publish-dist-manifest`; the assets
upload as-is with their computed sha256 recorded in the job summary for
provenance.

## What To Read Next

- {doc}`artifacts-and-outputs` — chain outputs and the optional integrity
  manifest.
- {doc}`permissions-and-secrets` — the caller-permission union and token-secret
  model.
- {doc}`security-model` — why no third-party action holds a secret.
- {doc}`troubleshooting` — environment, DOI, and digest-verification failure
  modes.
