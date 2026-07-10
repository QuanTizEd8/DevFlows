# DevFlows

DevFlows is a catalog of reusable, versioned, security-hardened GitHub Actions
workflows that other repositories consume as modular building blocks. Each
workflow exposes a small typed interface, pins its third-party actions to commit
SHAs, and follows least-privilege permissions. The catalog is organized as a
general-purpose core (document conversion, container image builds, repository
writeback) plus an emerging research-software tier (paper building and
publishing), so a project can adopt one workflow or compose several.

> **Status: pre-release.** No versions have been published yet and interfaces
> may change. See [Versioning and pinning](#versioning-and-pinning) below.

## Promoted workflows

| Workflow                                    | What it does                                                                                                    |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `.github/workflows/pandoc.yaml`             | Convert documents with official Pandoc Docker images, with checkout, artifact, and optional writeback channels. |
| `.github/workflows/build-devcontainer.yaml` | Build platform-specific devcontainer images and optionally merge them into a multi-arch image tag.              |
| `.github/workflows/writeback.yaml`          | Commit a validated writeback payload artifact back to a repository branch.                                      |

Every other workflow lives under `workflows/_drafts/` and is not part of the
public catalog until it is reviewed, documented, tested, and promoted.

## Usage

Reusable workflows are called at the job level with `jobs.<job_id>.uses`:

```yaml
jobs:
  convert:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v1.0.0
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=output/readme.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: readme-html
      artifact-upload-path: output/readme.html
```

Pin to an **exact per-workflow tag** (`@pandoc/v1.0.0`) or a **commit SHA**
(`@<40-char-sha>`) for reproducible, supply-chain-safe builds. The tag above is
illustrative: no versions are published yet, so check the repository's released
tags before wiring a workflow into CI.

## Versioning and pinning

Each workflow has its own independent version line and release history; the
repository does not share one global version across workflows.

- Per-workflow tags are scoped by workflow ID: `<id>/vX.Y.Z` (for example
  `pandoc/v1.0.0`, `writeback/v1.2.3`).
- Within a major version, promoted workflows avoid breaking existing callers.
  Breaking interface changes ship in a new major line.
- The project is **pre-release**: no tags are published yet and interfaces may
  still change before the first release.

## Documentation

Full user and developer documentation is published on GitHub Pages:

<https://quantized8.github.io/DevFlows/>

It covers calling workflows, per-workflow input/secret/output references,
versioning, permissions, and the maintainer development guide.

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
