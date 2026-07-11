# DevFlows

DevFlows is a catalog of **13 reusable, versioned, security-hardened GitHub
Actions workflows** — maintained as independently versioned building blocks that
other repositories consume. The catalog spans six categories: **Containers**,
**Documents**, **Pages**, **Python**, **Publishing**, and **Utilities**. Adopt a
single workflow, or compose several into a chain.

```{admonition} Pre-release
:class: warning
No versions have been published yet and interfaces may change. Every workflow is
pre-1.0 (`0.x`) — pin an exact release tag or a commit SHA.
```

````{grid} 1 1 2 2
:gutter: 3

```{grid-item-card} Use the workflows
:link: user-guide/index
:link-type: doc

Call DevFlows workflows from your own repository. The User Guide covers calling
conventions, versioning, permissions, secrets, and the consumer security model;
each workflow has a generated reference page for its exact interface.

+++
{doc}`Workflow catalog </reference/catalog>` · {doc}`User guide </user-guide/index>`
```

```{grid-item-card} Maintain the catalog
:link: dev-guide/index
:link-type: doc

Add or evolve workflows, tooling, tests, and releases. The Developer Guide
covers the source-of-truth model, the `devflows` CLI, and the generate/validate
pipeline that keeps `.github/workflows/` in sync with `workflows/<id>/`.
```

````

## The catalog at a glance

Every workflow links to its generated reference page — inputs, secrets, outputs,
the caller permission union, examples, and test scenarios. See the full
{doc}`workflow catalog </reference/catalog>` for the complete list.

**Python** — {doc}`python-build </reference/workflows/python-build>` ·
{doc}`python-test </reference/workflows/python-test>` ·
{doc}`python-lint </reference/workflows/python-lint>` ·
{doc}`pypi-publish </reference/workflows/pypi-publish>` ·
{doc}`anaconda-publish </reference/workflows/anaconda-publish>`

**Documents** — {doc}`pandoc </reference/workflows/pandoc>` ·
{doc}`docs-build </reference/workflows/docs-build>` ·
{doc}`paper-openjournals </reference/workflows/paper-openjournals>`

**Pages** — {doc}`deploy-pages </reference/workflows/deploy-pages>`

**Publishing** — {doc}`zenodo-release </reference/workflows/zenodo-release>`

**Containers** —
{doc}`build-devcontainer </reference/workflows/build-devcontainer>` ·
{doc}`binder-build </reference/workflows/binder-build>`

**Utilities** — {doc}`writeback </reference/workflows/writeback>`

## Minimal usage

Reusable workflows are called at the job level with `jobs.<job_id>.uses`:

```yaml
jobs:
  convert:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=output/readme.html README.md
```

Pin every call to an exact per-workflow tag (`@<id>/vX.Y.Z`) or a commit SHA.
`vX.Y.Z` is a placeholder — no versions are published yet. See
{doc}`versioning </user-guide/versioning>` for the tag mechanics.

```{toctree}
:caption: Using DevFlows
:maxdepth: 2

reference/catalog
user-guide/index
```

```{toctree}
:caption: Maintaining DevFlows
:maxdepth: 1

dev-guide/index
```
