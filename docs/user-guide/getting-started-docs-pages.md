# Getting Started: Build Docs and Deploy to GitHub Pages

This page walks through the documentation-to-Pages chain: `docs-build` builds a
site in a caller-selected environment, and `deploy-pages` deploys it to GitHub
Pages under a protected environment over OIDC. `deploy-pages` is the
composability keystone other builders chain into. The generated reference pages
are the authoritative source for every input, output, and the exact
caller-permission union:

- {doc}`Build Documentation </reference/workflows/docs-build>`
- {doc}`Deploy Pages </reference/workflows/deploy-pages>`

Replace every `vX.Y.Z` with a real released tag; DevFlows has no published tags
yet (see {doc}`versioning`).

## The Split: Build Read-Only, Deploy Elevated

The two workflows are deliberately separate so that every documentation build —
including builds on pull requests from forks — stays read-only, while the
elevated Pages token lives only in the deploy step:

```text
build-docs (docs-build)          contents: read, actions: read
  │  uploads a GitHub Pages artifact
  │  output: pages-artifact-name
  └──────────────► deploy-docs (deploy-pages)   pages: write, id-token: write
                     deploys the artifact by name
                     output: pages-url
```

`docs-build` never holds a write scope. When `pages-artifact-enabled: true` it
uploads the built site as a GitHub Pages artifact (via
`actions/upload-pages-artifact`) with no extra permissions. The deployment —
`pages: write` and `id-token: write` — lives entirely in `deploy-pages`.

Job-level permissions **replace** the workflow-level block, they do not merge
with it, so the deploy job must grant the full union `deploy-pages` declares
across its whole job tree: `contents: read` + `actions: read` (its package job)
plus `pages: write` + `id-token: write` (its deploy job). GitHub validates these
nested permissions at startup, so granting less fails the run before any job
starts. See {doc}`permissions-and-secrets`.

## The Worked Chain

This is the canonical DevFlows docs chain (the pattern in
`tests/fixtures/docs-build/pages-chain.yaml`): `docs-build` uploads the Pages
artifact, and `deploy-pages` deploys it by name with
`pages-artifact-enabled: false` (deploy-only mode — the site is already
packaged, so it must not re-package or check out).

```yaml
name: Build docs and deploy to GitHub Pages

on:
  push:
    branches: [main]

# docs-build stays read-only; the Pages deploy union lives on the deploy job.
permissions:
  contents: read
  actions: read

jobs:
  build-docs:
    uses: QuanTizEd8/DevFlows/.github/workflows/docs-build.yaml@docs-build/vX.Y.Z
    with:
      docs-tool: sphinx
      docs-environment: pip
      pip-install-targets: |
        sphinx
        furo
      sphinx-source-directory: docs
      docs-output-directory: _site
      # Upload the built site as a GitHub Pages artifact for the deploy-pages chain.
      pages-artifact-enabled: true

  deploy-docs:
    needs: build-docs
    permissions:
      contents: read
      actions: read
      pages: write
      id-token: write
    uses: QuanTizEd8/DevFlows/.github/workflows/deploy-pages.yaml@deploy-pages/vX.Y.Z
    with:
      pages-artifact-name: ${{ needs.build-docs.outputs.pages-artifact-name }}
      # Deploy-only mode: the site was already packaged by build-docs, so
      # deploy-pages must not re-package and must not check out.
      pages-artifact-enabled: false
      checkout-enabled: false
```

The default `pages-artifact-name` on both workflows is `github-pages`, which is
also `actions/deploy-pages`' expected default, so the chain works with zero
extra wiring; passing the output through explicitly keeps it robust if you
rename it.

## Choosing a Build Environment

`docs-environment` is required (there is no safe silent default). `docs-build`
supports five strategies — `pixi`, `uv`, `pip`, `micromamba`, and `container` —
and silently ignores inputs of the non-selected group, so one call site can
template several modes. A few useful knobs:

- `docs-tool`: `sphinx` (first-class) or `mkdocs`.
- `docs-warnings-as-errors: true` adds `-W --keep-going` (Sphinx) or `--strict`
  (MkDocs) so a warning fails the build.
- `docs-linkcheck-enabled: true` runs Sphinx's `linkcheck` builder (Sphinx only;
  requesting it with MkDocs fails validation).
- Extensions that need full git history (for example
  `sphinx-last-updated-by-git`) need `checkout-fetch-depth: 0`.

The {doc}`Build Documentation reference </reference/workflows/docs-build>` has
the `uv`, `pip`, and `container` examples and the full input table.

## Serving the Deployed URL

`deploy-pages` exposes the live site as the `pages-url` output (empty when
`pages-deploy-enabled` is false or the deploy job was skipped, so guard on a
non-empty value). A downstream job can surface it:

```yaml
report:
  needs: deploy-docs
  if: ${{ !cancelled() && needs.deploy-docs.outputs.pages-url != '' }}
  runs-on: ubuntu-latest
  steps:
    - run: echo "Deployed to ${{ needs.deploy-docs.outputs.pages-url }}"
```

## Deploying a Non-DevFlows Build

If your site is not built by `docs-build`, hand `deploy-pages` a site
**directory** instead: upload the built site as a plain artifact, then have
`deploy-pages` ingest it through its `artifact-download` channel and package it
itself.

```yaml
deploy:
  needs: build
  permissions:
    contents: read
    actions: read
    pages: write
    id-token: write
  uses: QuanTizEd8/DevFlows/.github/workflows/deploy-pages.yaml@deploy-pages/vX.Y.Z
  with:
    checkout-enabled: false
    artifact-download-enabled: true
    artifact-download-name: site
    artifact-download-path: _site
    pages-path: _site
```

Note that plain `upload-artifact` artifacts are not Pages-deployable on their
own — that is why deploy-only mode (`pages-artifact-enabled: false`) is reserved
for artifacts an earlier `upload-pages-artifact` step already produced in the
same run.

## Before the First Deploy

- Enable GitHub Pages with source **GitHub Actions** in repository settings.
  `configure-pages` fails with a clear error otherwise; one-time enablement is
  deliberately not automated because it would need a PAT.
- A reusable workflow cannot impose caller-level concurrency. To keep a single
  deployment in flight, add a workflow-level concurrency group in the caller:

  ```yaml
  concurrency:
    group: pages
    cancel-in-progress: false
  ```

- For a pull-request check, set `pages-deploy-enabled: false` to validate and
  package the Pages artifact without deploying.

## What To Read Next

- {doc}`artifacts-and-outputs` — the GitHub Pages artifact channel and chain
  outputs.
- {doc}`permissions-and-secrets` — the caller-permission union and OIDC.
- {doc}`security-model` — why the elevated Pages deploy is isolated.
- {doc}`troubleshooting` — Pages and environment failure modes.
