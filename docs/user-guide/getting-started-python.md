# Getting Started: Python Build, Test, and Publish

This page walks through the Python tier as a single worked pipeline:
`python-build` produces distribution artifacts, `python-test` installs and
exercises them across a matrix, and `pypi-publish` and `anaconda-publish`
release them to their indexes. Each workflow has a generated reference page that
is the authoritative source for every input, secret, output, and the exact
caller-permission union; this page shows how they fit together and links out for
the detail:

- {doc}`Python Build </reference/workflows/python-build>`
- {doc}`Python Test </reference/workflows/python-test>`
- {doc}`PyPI Publish </reference/workflows/pypi-publish>`
- {doc}`Anaconda Publish </reference/workflows/anaconda-publish>`

Replace every `vX.Y.Z` with a real released tag. DevFlows has no published tags
yet (all workflows are pre-1.0), so pin an exact `<workflow-id>/vX.Y.Z` release
tag or a commit SHA. See {doc}`versioning`.

## The Job Graph

The four workflows chain through job outputs and named artifacts:

```text
build (python-build)
  │  outputs: dist-manifest, package-version,
  │           sdist-artifact-name, wheels-artifact-name, conda-artifact-name
  ├──────────────► test (python-test)          installs the wheelhouse, runs pytest
  ├──────────────► pypi (pypi-publish)          OIDC trusted publishing to PyPI
  └──────────────► anaconda (anaconda-publish)  token-authenticated conda upload
```

`python-build` is the only job that builds. Everything downstream ingests its
artifacts through the shared `artifact-download-*` channel and reads its outputs
through `needs.build.outputs.*`. The `dist-manifest` output is the integrity
contract every publisher verifies before an irreversible upload; see
{doc}`artifacts-and-outputs`.

## Build, Then Test the Built Wheels

`python-build` emits a flat wheelhouse artifact plus a `dist-manifest`.
`python-test` installs the compatible wheel from that wheelhouse (offline,
`--no-index`) and runs the caller's test command across a matrix of runners and
Python versions.

Both workflows are read-only. Each statically declares `contents: read` and
`actions: read` (the `actions: read` scope is required by the generated artifact
channels even when a feature is off), so every calling job must grant that
union. GitHub validates a called workflow's nested job permissions at startup,
before any `if:` runs, so a missing scope fails the whole run before any job
starts — see {doc}`permissions-and-secrets`.

```yaml
name: Build and test

on:
  push:
  pull_request:

permissions: {}

jobs:
  build:
    uses: QuanTizEd8/DevFlows/.github/workflows/python-build.yaml@python-build/vX.Y.Z
    permissions:
      contents: read
      actions: read
    with:
      build-tool: uv
      build-sdist-enabled: true
      build-wheel-enabled: true
      dist-artifact-prefix: my-package

  test:
    needs: build
    uses: QuanTizEd8/DevFlows/.github/workflows/python-test.yaml@python-test/vX.Y.Z
    permissions:
      contents: read
      actions: read
    with:
      test-matrix: |
        [
          { "runner": "ubuntu-latest", "python-version": "3.11" },
          { "runner": "ubuntu-latest", "python-version": "3.13" },
          { "runner": "macos-latest", "python-version": "3.13" }
        ]
      # Install the wheel python-build produced instead of re-building from source.
      test-install-source: artifact
      artifact-download-enabled: true
      artifact-download-name: ${{ needs.build.outputs.wheels-artifact-name }}
      artifact-download-path: dist
      test-dist-path: dist
      test-dependencies: |
        pytest
      test-command: pytest
```

Notes on the handoff:

- `artifact-download-name` is fed `needs.build.outputs.wheels-artifact-name`.
  That output is the empty string when no wheels were built, so a broken chain
  fails loudly rather than testing nothing.
- The install is offline. Runtime dependencies must be in the wheelhouse or
  supplied through `test-dependencies`.
- To install from source instead (no build step), drop the artifact inputs and
  leave `test-install-source` at its `source` default.

## Coverage Lives in the Caller

`python-test` does not upload coverage. Have the test command emit coverage
files, add them to `report-path`, and run a caller-side job that holds
`id-token: write` and hands the files to Codecov over OIDC. This keeps the
reusable test job at `contents: read` — the elevated scope never touches the
matrix legs. The full pattern is in the "Chain from python-build and upload
coverage" example on the
{doc}`Python Test reference </reference/workflows/python-test>`.

## Publish to PyPI with OIDC Trusted Publishing

`pypi-publish` uploads a digest-verified sdist and wheel set to PyPI or TestPyPI
via **OIDC trusted publishing only**. There is deliberately no token secret: the
publish job mints a short-lived OIDC token (`id-token: write`) and PyPI issues
PEP 740 attestations. Because the publish job declares `id-token: write`
statically, every calling job must grant the full union — `contents: read`,
`actions: read`, and `id-token: write` — even for a dry-run call.

Two inputs are required and have no default, on purpose (publishing is
irreversible):

- `publish-dist-manifest` — chain `needs.build.outputs.dist-manifest`. Only
  files listed in the manifest, byte-for-byte sha256- and size-matched, are ever
  uploaded.
- `publish-dist-path` — the directory the distributions were downloaded into.

`publish-environment-name` binds the publish job to a GitHub environment; put
required reviewers and branch rules there to gate releases. The recommended
release shape stages to TestPyPI first, proves the release installs and imports,
then promotes to PyPI as a second, separately-gated call:

```yaml
name: Release to PyPI

on:
  release:
    types: [published]

permissions: {}

jobs:
  build:
    uses: QuanTizEd8/DevFlows/.github/workflows/python-build.yaml@python-build/vX.Y.Z
    permissions:
      contents: read
      actions: read
    with:
      build-sdist-enabled: true
      build-wheel-enabled: true
      dist-artifact-prefix: my-package

  stage-testpypi:
    needs: build
    uses: QuanTizEd8/DevFlows/.github/workflows/pypi-publish.yaml@pypi-publish/vX.Y.Z
    permissions:
      contents: read
      actions: read
      id-token: write
    with:
      publish-index: testpypi
      publish-environment-name: testpypi
      # Chain the integrity contract and the version guard straight from the build.
      publish-dist-manifest: ${{ needs.build.outputs.dist-manifest }}
      publish-expected-version: ${{ needs.build.outputs.package-version }}
      artifact-download-enabled: true
      artifact-download-pattern: my-package-{sdist,wheels}
      artifact-download-merge-multiple: true
      artifact-download-path: dist
      publish-dist-path: dist
      # Prove the staged release installs and imports before promoting it.
      install-check-enabled: true
      install-check-import-names: |
        my_package

  release-pypi:
    needs: [build, stage-testpypi]
    uses: QuanTizEd8/DevFlows/.github/workflows/pypi-publish.yaml@pypi-publish/vX.Y.Z
    permissions:
      contents: read
      actions: read
      id-token: write
    with:
      publish-index: pypi
      publish-environment-name: pypi
      publish-dist-manifest: ${{ needs.build.outputs.dist-manifest }}
      publish-expected-version: ${{ needs.build.outputs.package-version }}
      artifact-download-enabled: true
      artifact-download-pattern: my-package-{sdist,wheels}
      artifact-download-merge-multiple: true
      artifact-download-path: dist
      publish-dist-path: dist
```

Before the first run, register a **trusted publisher** on PyPI (and separately
on TestPyPI) for your repository, your calling workflow's filename, and the
environment name you pass as `publish-environment-name`. The staging and release
calls target different indexes and different environments, so each gets its own
protection rules. Set `publish-dry-run-enabled: true` for a pull-request check:
it downloads and digest-verifies the distributions but skips the publish job
entirely, so no OIDC token is minted, no environment is bound, and no required
reviewer is pinged. See {doc}`security-model` for the credential model and
{doc}`troubleshooting` for trusted-publisher and environment failure modes.

## Publish a Conda Channel to anaconda.org

anaconda.org has no OIDC, so `anaconda-publish` uses a long-lived token secret —
with least exposure as the compensating control. The token is declared
`required: false` (dry-run needs none) and reaches exactly one CLI step per
credentialed job. The recommended pattern stores the token as a GitHub
**environment secret** on the `anaconda-*` environments and passes it with
`secrets: inherit`; an explicit `secrets:` mapping is evaluated in the caller's
environment-less context and would need a repository or organization secret
instead. `anaconda-publish` never requests a write scope — all authority to
mutate anaconda.org comes from the token — so the caller grants only
`contents: read` and `actions: read`.

Publishing is staged: `upload` always lands packages on a staging label, and a
separately-gated `promote` job relabels them to the install label. Bind each
operation to its own environment so protection rules scale with blast radius
(strict reviewers on the release environment):

```yaml
name: Release conda packages

on:
  push:
    tags: ["v*"]

permissions: {}

jobs:
  build:
    permissions:
      contents: read
      actions: read
    uses: QuanTizEd8/DevFlows/.github/workflows/python-build.yaml@python-build/vX.Y.Z
    with:
      conda-enabled: true
      conda-recipe-path: recipe.yaml
      dist-artifact-prefix: my-package

  publish:
    needs: build
    # Chaining convention: run only when the upstream conda channel exists.
    if: ${{ !cancelled() && needs.build.outputs.conda-artifact-name != '' }}
    permissions:
      contents: read
      actions: read
    uses: QuanTizEd8/DevFlows/.github/workflows/anaconda-publish.yaml@anaconda-publish/vX.Y.Z
    # zenodo-* and anaconda-* tokens live as environment secrets on the bound
    # environments; secrets: inherit passes them through.
    secrets: inherit
    with:
      publish-owner: my-anaconda-org
      upload-enabled: true
      promote-enabled: true
      upload-label: staging
      promote-label: main
      artifact-download-enabled: true
      artifact-download-name: ${{ needs.build.outputs.conda-artifact-name }}
      artifact-download-path: conda-channel
      publish-dist-path: conda-channel
      publish-dist-manifest: ${{ needs.build.outputs.dist-manifest }}
      publish-expected-version: ${{ needs.build.outputs.package-version }}
```

`publish-dry-run-enabled: true` rehearses the whole plan — digest verification
and spec derivation — with no token and no environment bound. Rehearse an
irreversible removal or promotion this way first. The
{doc}`Anaconda Publish reference </reference/workflows/anaconda-publish>`
documents the promote-only recovery path and the destructive `maintain` mode.

## What To Read Next

- {doc}`artifacts-and-outputs` — the `dist-manifest` integrity contract and the
  chaining conventions in depth.
- {doc}`permissions-and-secrets` — the caller-permission union and the
  OIDC-versus-token credential model.
- {doc}`security-model` — why these publishers are safe to trust.
- {doc}`troubleshooting` — publishing-tier failure modes.
