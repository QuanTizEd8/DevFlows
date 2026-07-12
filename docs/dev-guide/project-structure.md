# Project Structure

DevFlows separates source files, generated files, fixtures, and tests so that
workflow promotion stays reviewable.

The catalog currently holds 13 active workflows — `anaconda-publish`,
`binder-build`, `deploy-pages`, `devcontainer-build`, `docs-build`, `pandoc`,
`paper-openjournals`, `pypi-publish`, `python-build`, `python-lint`,
`python-test`, `writeback`, and `zenodo-release` — each a
`workflows/<workflow-id>/` directory.

## Important Directories

| path                                                   | purpose                                                                            |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `workflows/<workflow-id>/workflow.yaml`                | Source reusable workflow for a promoted workflow.                                  |
| `workflows/<workflow-id>/devflow.yaml`                 | Metadata, release config, docs fields, examples, and tests.                        |
| `workflows/<workflow-id>/scripts/`                     | Source support scripts inlined into the published workflow at sync time.           |
| `.github/workflows/<workflow-id>.yaml`                 | Generated publish location required by GitHub.                                     |
| `.github/workflows/devflows-scenarios-<id>.yaml`       | Generated hosted scenario test workflow (one per catalog workflow).                |
| `.github/workflows/devflows-scenarios-<id>.local.yaml` | Generated local scenario test workflow (one per workflow with local scenarios).    |
| `.github/workflows/devflows-*.yaml`                    | The repository's own internal workflows (CI, docs, release, CodeQL, devcontainer). |
| `harness/scenarios/`                                   | Scenario harness scripts run by the generated scenario workflows.                  |
| `src/devflows/`                                        | Python CLI and generation logic.                                                   |
| `tests/`                                               | Python unit tests for DevFlows tooling.                                            |
| `tests/fixtures/`                                      | Example caller workflows rendered into docs.                                       |
| `tests/scenarios/`                                     | Checked-in test inputs used by workflow scenarios.                                 |
| `docs/user-guide/`                                     | Hand-written consumer documentation.                                               |
| `docs/dev-guide/`                                      | Hand-written maintainer documentation (this tree).                                 |
| `docs/reference/`                                      | Ignored generated workflow catalog and reference pages created during docs builds. |

There is **no** `workflows/_drafts/` directory in the tree. `_drafts` is an
optional, currently-empty mechanism:
`catalog.workflow_dirs(include_drafts=True)` (surfaced as
`devflows validate --include-drafts`) would load workflows from a
`workflows/_drafts/` directory if one existed, but nothing in the default
catalog path opts into it. All 14 workflows above are promoted, active, and
released.

## Script Modules

A workflow's `scripts/` directory is not limited to one file per job. Larger
workflows split their logic into focused Python modules that jobs import — for
example `anaconda-publish/scripts/` has `parsing.py`, `arguments.py`,
`manifest.py`, `digest.py`, `commands.py`, plus the per-job entrypoints
`validate-inputs.py`, `verify-dist.py`, `reverify.py`, `upload.py`,
`promote.py`, and `maintain.py`. At sync time each job's materialize step
inlines **only** the modules that job references (see
{doc}`workflow-lifecycle`), so a shared module is not re-inlined into every job.
Jobs declare the modules they need with
`# imports ${DEVFLOWS_SCRIPT_ROOT}/<id>/<module>.py` comment lines in their
`run` block; the generator scans those references. This per-job slicing is what
keeps each generated workflow under the size cap (see {doc}`testing`).

A `reverify.py` module is the common name for a credentialed job's tokenless
time-of-check/time-of-use re-verification step (publishing workflows re-hash the
downloaded distributions against the caller's manifest immediately before the
single credentialed upload step).

## Source Versus Generated Files

Edit source files first:

- workflow behavior: `workflows/<workflow-id>/workflow.yaml`
- workflow support scripts: `workflows/<workflow-id>/scripts/...`
- metadata/docs/tests: `workflows/<workflow-id>/devflow.yaml`
- docs guide pages: `docs/user-guide/...` and `docs/dev-guide/...`
- generator behavior: `src/devflows/...`

Then regenerate committed generated files:

```bash
pixi run -- devflows sync
pixi run -- devflows test-generate
```

Reference docs are generated as ignored build output by:

```bash
pixi run -- devflows docs
```

Do not hand-edit generated workflow copies, scenario workflows, or reference
pages unless you are debugging a generator. The `lint` task checks committed
generated-file drift and verifies reference documentation generation succeeds.

## Draft Workflows

Drafts are an **optional, currently-unused** mechanism, not a live directory. If
a `workflows/_drafts/` directory existed, workflows placed under it would be
skipped by the default catalog load and picked up only with
`devflows validate --include-drafts`
(`catalog.workflow_dirs(include_drafts=True)`). They would not be synced to
`.github/workflows` as promoted workflows. Today the catalog has no `_drafts/`
directory — a new workflow is authored directly under `workflows/<workflow-id>/`
and promoted once its interface, metadata, documentation, tests, and release
behavior have been reviewed (see {doc}`add-a-workflow`).
