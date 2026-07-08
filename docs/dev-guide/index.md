# Developer Guide

This guide is for people maintaining DevFlows itself: adding workflows,
improving the tooling, writing tests, updating docs, and preparing releases.

## Quickstart

The repository is organized around a catalog of workflow definitions. The
catalog source lives under `workflows/<workflow-id>`, while files that GitHub
needs under `.github/workflows` are generated.

### The Short Version

1. Work inside the devcontainer, or install Pixi locally.
2. Keep active workflow source under `workflows/<workflow-id>/workflow.yaml`.
3. Keep workflow metadata under `workflows/<workflow-id>/devflow.yaml`.
4. Treat `.github/workflows/<workflow-id>.yaml` and generated scenario workflows
   as committed generated files; treat `docs/reference/` as ignored build
   output.
5. Add scenario tests for every promoted workflow path you care about.
6. Run the full checks before opening a pull request:

```bash
task lint
task test
task test:local
task docs
task release:dry-run
```

Pixi task equivalents are available as `pixi run lint`, `pixi run test`,
`pixi run test-local`, `pixi run docs`, and `pixi run release-dry-run`.

### Command Map

| command                    | purpose                                                                                       |
| -------------------------- | --------------------------------------------------------------------------------------------- |
| `pixi run fmt`             | Format Python, shell, YAML, Markdown, JSON, and TOML.                                         |
| `pixi run lint`            | Validate metadata, generated files, Actions syntax, formatting, shell, and security findings. |
| `pixi run test`            | Run Python unit tests.                                                                        |
| `pixi run test-local`      | Generate and run local scenario tests through `act`.                                          |
| `pixi run docs`            | Generate reference pages and build Sphinx HTML.                                               |
| `pixi run docs-serve`      | Serve docs locally with live rebuilds.                                                        |
| `pixi run release-dry-run` | Validate release-please configuration.                                                        |

### What To Read Next

```{toctree}
:maxdepth: 2

environment
project-structure
workflow-lifecycle
metadata
testing
documentation
release
ci
troubleshooting
```
