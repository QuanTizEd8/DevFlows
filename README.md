# DevFlows

DevFlows is a catalog of **14 reusable, versioned, security-hardened GitHub
Actions workflows** that other repositories consume as modular building blocks.
The catalog spans six categories — **Containers**, **Documents**, **Pages**,
**Python**, **Publishing**, and **Utilities** — covering a full Python CI tier
(`python-build`, `python-test`, `python-lint`), package and research publishing
(`pypi-publish`, `anaconda-publish`, `zenodo-release`), document and paper
building (`pandoc`, `docs-build`, `paper-openjournals`), GitHub Pages deployment
(`deploy-pages`), container/Binder image builds and runs (`build-devcontainer`,
`binder-build`, `devcontainer-run`), and repository writeback (`writeback`).
Each workflow exposes a small typed interface, pins its third-party actions to
commit SHAs, and runs under least-privilege permissions, so a project can adopt
a single workflow or compose several into a chain.

> **Status: pre-release.** No versions have been published yet and interfaces
> may change. See [Versioning and pinning](#versioning-and-pinning) below.

## Why these workflows are safe

Security is a first-class feature of the catalog, not an afterthought:

- **SHA-pinned actions.** Every third-party action is pinned to a full commit
  SHA from a single registry and kept current by Renovate — no floating tags.
- **Inlined, ASCII-only scripts.** Workflow logic is inlined as ASCII-only
  scripts (generated workflows are capped at 115,000 bytes), so there is no
  hidden dependency fetched at runtime.
- **Least-privilege per-job permissions.** Each job declares only the token
  scopes it needs. Because GitHub validates every nested job's `permissions` at
  workflow **startup** (before any `if:` is evaluated), a caller must grant the
  full documented permission union or the call fails before any job runs.
- **OIDC trusted publishing.** `pypi-publish` and `deploy-pages` authenticate
  with short-lived OIDC tokens (`id-token: write`) — no long-lived secrets.
- **Environment gating.** Every irreversible operation runs in an isolated,
  GitHub-environment-protected job so reviewers and branch rules can guard it.
- **Dry-run job-level skip.** Publishing workflows expose a dry run that skips
  the credentialed job entirely rather than merely short-circuiting a step.
- **TOCTOU digest verification.** Publishers re-verify each artifact against the
  `sha256` `dist-manifest` emitted by `python-build` before any upload, closing
  the time-of-check/time-of-use gap.

See the
[security model](https://quantized8.github.io/DevFlows/user-guide/security-model.html)
for the full consumer-facing narrative.

## Workflow catalog

All 14 workflows are promoted and part of the public catalog. Each links to its
generated reference page (inputs, secrets, outputs, the caller permission union,
examples, and test scenarios).

| Category   | Workflow             | Summary                                                                                                                                           | Reference                                                                                      |
| ---------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Python     | `python-build`       | Build sdist, pure and cibuildwheel wheels, and conda packages into named artifacts with `sha256` digests and a JSON manifest for publishing.      | [reference](https://quantized8.github.io/DevFlows/reference/workflows/python-build.html)       |
| Python     | `python-test`        | Install from source or a built distribution and run the caller's test command across a validated runner/Python-version matrix.                    | [reference](https://quantized8.github.io/DevFlows/reference/workflows/python-test.html)        |
| Python     | `python-lint`        | Run `ruff check`, `ruff format --check`, and a selectable type checker (mypy/pyright/ty) as one read-only gate with annotations.                  | [reference](https://quantized8.github.io/DevFlows/reference/workflows/python-lint.html)        |
| Documents  | `pandoc`             | Convert documents with official Pandoc Docker images, with uniform checkout, artifact, and optional writeback channels.                           | [reference](https://quantized8.github.io/DevFlows/reference/workflows/pandoc.html)             |
| Documents  | `docs-build`         | Build documentation (Sphinx-first, MkDocs supported) in a caller-selected environment and emit a regular and/or GitHub Pages artifact.            | [reference](https://quantized8.github.io/DevFlows/reference/workflows/docs-build.html)         |
| Documents  | `paper-openjournals` | Build a JOSS, JOSE, or ReScience C paper from Markdown with the pinned `openjournals/inara` container, collecting requested flavors.              | [reference](https://quantized8.github.io/DevFlows/reference/workflows/paper-openjournals.html) |
| Pages      | `deploy-pages`       | Package a built static site into a GitHub Pages artifact and deploy it via OIDC under a protected environment — the composability keystone.       | [reference](https://quantized8.github.io/DevFlows/reference/workflows/deploy-pages.html)       |
| Publishing | `pypi-publish`       | Publish a digest-verified sdist/wheel set to PyPI or TestPyPI via OIDC trusted publishing only, with PEP 740 attestations and a dry run.          | [reference](https://quantized8.github.io/DevFlows/reference/workflows/pypi-publish.html)       |
| Publishing | `anaconda-publish`   | Publish `python-build`'s conda artifact to anaconda.org under a staging label and promote it, every mutating step digest-verified and gated.      | [reference](https://quantized8.github.io/DevFlows/reference/workflows/anaconda-publish.html)   |
| Publishing | `zenodo-release`     | Cut a research-software release from a tag: create/update a GitHub Release and a matching Zenodo deposition with a reserved-or-registered DOI.    | [reference](https://quantized8.github.io/DevFlows/reference/workflows/zenodo-release.html)     |
| Containers | `build-devcontainer` | Build platform-specific devcontainer images and optionally merge them into a multi-arch image tag.                                                | [reference](https://quantized8.github.io/DevFlows/reference/workflows/build-devcontainer.html) |
| Containers | `binder-build`       | Build a Binder (repo2docker) image credential-free, push it from an isolated gated job with an SLSA provenance attestation and pinned Dockerfile. | [reference](https://quantized8.github.io/DevFlows/reference/workflows/binder-build.html)       |
| Containers | `devcontainer-run`   | Run a command inside a prebuilt devcontainer image without rebuilding, applying its `devcontainer.metadata` features, hooks, user, and env.       | [reference](https://quantized8.github.io/DevFlows/reference/workflows/devcontainer-run.html)   |
| Utilities  | `writeback`          | Commit a validated writeback payload artifact to a repository branch.                                                                             | [reference](https://quantized8.github.io/DevFlows/reference/workflows/writeback.html)          |

## Usage

Reusable workflows are called at the job level with `jobs.<job_id>.uses`:

```yaml
jobs:
  convert:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=output/readme.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: readme-html
      artifact-upload-path: output/readme.html
```

Pin to an **exact per-workflow tag** (`@<id>/vX.Y.Z`) or a **commit SHA**
(`@<40-char-sha>`) for reproducible, supply-chain-safe builds. The reference
above uses the placeholder `pandoc/vX.Y.Z`: no versions are published yet, so
check the repository's released tags before wiring a workflow into CI.

## Versioning and pinning

Each workflow has its own independent version line and release history; the
repository does not share one global version across workflows.

- Per-workflow tags are scoped by workflow ID: `<id>/vX.Y.Z` (for example
  `pandoc/vX.Y.Z`, `python-build/vX.Y.Z`).
- Every workflow is currently **pre-1.0 (`0.x`)**: pin an exact release tag or a
  commit SHA. Moving major tags (`<id>/vN`) become available once a workflow
  reaches its `1.0.0` release.
- The project is **pre-release**: no tags are published yet and interfaces may
  still change before the first release.

## Documentation

Full user and developer documentation is published on GitHub Pages:

<https://quantized8.github.io/DevFlows/>

It covers calling workflows, per-workflow input/secret/output references,
versioning, permissions, the consumer security model, and the maintainer
development guide.

## Development

DevFlows is source-of-truth driven: you edit workflow sources under
`workflows/<workflow-id>/` and regenerate the published copies in
`.github/workflows/`. Never edit the generated files directly.

Quickstart (use the devcontainer, or install [Pixi](https://pixi.sh) locally):

```bash
pixi install       # provision the toolchain
task lint          # validate metadata and check generated files are in sync
task test          # run unit tests
task docs          # generate and build documentation
```

The Taskfile is the single task registry; each task delegates to a pixi-provided
tool (for example `pixi run -- devflows ...`).

After changing a workflow source, regenerate the published outputs and commit
them alongside the source change:

```bash
task sync          # regenerate .github/workflows/ from workflows/<id>/
```

The `task lint` gate fails if the generated workflows, docs, or scenario tests
have drifted from their sources. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
full contributor guide and [SECURITY.md](SECURITY.md) for the security policy.

## License

DevFlows is licensed under the [Apache License 2.0](LICENSE).
