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
6. Regenerate committed generated files, then run the full checks before opening
   a pull request:

```bash
# Regenerate committed generated files after editing any workflow source.
task sync            # .github/workflows/<id>.yaml
task test-generate   # per-workflow scenario workflows

# Verify.
task lint            # includes validate + the --check drift guards
task test
task scenarios-local
task docs
task propagation-check   # only meaningful with DEVFLOWS_BASE_SHA set; CI always runs it
task release-check
```

`task lint` runs the generators with `--check`, so it fails if you forgot to
regenerate — the fix is `task sync` / `task test-generate` and commit the
result. `task propagation-check` is a no-op locally unless you set
`DEVFLOWS_BASE_SHA`; CI runs it on every pull request (see {doc}`release`).

`task` is the single entry point for every project command; each task runs the
underlying tool from the Pixi environment (`pixi run -- <tool>`). Install `task`
from the devcontainer or with `brew install go-task` (Pixi provides everything
else).

### Command Map

| command                  | purpose                                                                                      |
| ------------------------ | -------------------------------------------------------------------------------------------- |
| `task fmt`               | Format Python, shell, YAML, Markdown, JSON, and TOML.                                        |
| `task validate`          | Validate workflow catalog metadata (`devflows validate`).                                    |
| `task sync`              | Regenerate published `.github/workflows/<id>.yaml` from catalog sources.                     |
| `task test-generate`     | Regenerate the per-workflow hosted and local scenario workflows.                             |
| `task lint`              | Validate metadata, generated-file drift, Actions syntax, formatting, shell, and secrets.     |
| `task test`              | Run Python unit tests.                                                                       |
| `task test-contract`     | Run the network adapter contract test against every pinned action's `action.yml`.            |
| `task scenarios-local`   | Generate and run local scenario tests through `act`.                                         |
| `task docs`              | Generate reference pages and build Sphinx HTML.                                              |
| `task docs-serve`        | Serve docs locally with live rebuilds.                                                       |
| `task propagation-check` | Fail when a shared-generator change alters a published workflow with no attributable source. |
| `task release-check`     | Validate release-please configuration against the catalog.                                   |

Every task delegates to a Pixi-provided tool; see {doc}`cli-reference` for the
underlying `devflows` subcommands and their flags.

### What To Read Next

```{toctree}
:maxdepth: 2

environment
project-structure
workflow-lifecycle
add-a-workflow
metadata
adapter-and-action-pins
cli-reference
testing
documentation
ci
publishing-conventions
release
troubleshooting
```
