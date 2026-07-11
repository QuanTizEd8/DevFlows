# Project Structure

DevFlows separates source files, generated files, fixtures, and tests so that
workflow promotion stays reviewable.

## Important Directories

| path                                                   | purpose                                                                            |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `workflows/<workflow-id>/workflow.yaml`                | Source reusable workflow for a promoted workflow.                                  |
| `workflows/<workflow-id>/devflow.yaml`                 | Metadata, release config, docs fields, examples, and tests.                        |
| `workflows/<workflow-id>/scripts/`                     | Source support scripts inlined into the published workflow at sync time.           |
| `workflows/_drafts/`                                   | Inherited or experimental workflows not yet promoted.                              |
| `.github/workflows/<workflow-id>.yaml`                 | Generated publish location required by GitHub.                                     |
| `.github/workflows/devflows-scenarios-<id>.yaml`       | Generated hosted scenario test workflow (one per catalog workflow).                |
| `.github/workflows/devflows-scenarios-<id>.local.yaml` | Generated local scenario test workflow (one per workflow with local scenarios).    |
| `harness/scenarios/`                                   | Scenario harness scripts run by the generated scenario workflows.                  |
| `src/devflows/`                                        | Python CLI and generation logic.                                                   |
| `tests/`                                               | Python unit tests for DevFlows tooling.                                            |
| `tests/fixtures/`                                      | Example caller workflows rendered into docs.                                       |
| `tests/scenarios/`                                     | Checked-in test inputs used by workflow scenarios.                                 |
| `docs/`                                                | Sphinx documentation source.                                                       |
| `docs/reference/`                                      | Ignored generated workflow catalog and reference pages created during docs builds. |

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

Draft workflows live under `workflows/_drafts`. They are not loaded into the
active catalog by default and are not synced to `.github/workflows` as promoted
workflows. A draft can be promoted only after its interface, metadata,
documentation, tests, and release behavior have been reviewed.
