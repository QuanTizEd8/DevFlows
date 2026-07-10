# Contributing to DevFlows

Thanks for your interest in improving DevFlows. This guide covers the local
development setup, the source-vs-generated model that the project depends on,
and the commit conventions that drive releases.

## Development environment

DevFlows uses [Pixi](https://pixi.sh) for reproducible tooling. There are two
supported paths:

- **Devcontainer (recommended).** Open the repository in the provided
  devcontainer. It ships the system tools and Docker access needed for local
  workflow scenario tests, with Pixi already available.
- **Local Pixi.** Install Pixi, then run `pixi install` in the repository root
  to provision Python, pytest, Sphinx, actionlint, yamllint, prettier, taplo,
  release-please, zizmor, and the project's dependencies.

## Task entry points

Common tasks are exposed both through Pixi and the Taskfile:

```bash
pixi run lint    # or: task lint    -- validation + drift checks + linters
pixi run test    # or: task test    -- unit tests (pytest)
pixi run docs    # or: task docs    -- generate + build the documentation
pixi run fmt     #                  -- auto-format sources, docs, and config
```

Local GitHub Actions scenario tests (require Docker + `act`):

```bash
pixi run test-local   # or: task test:local
```

`pixi run lint` is the gate: it runs `devflows validate`, the `--check`
variants of `sync`, `docs`, and `test-generate`, plus actionlint, ruff,
yamllint, taplo, shell linting, and zizmor. Run it before opening a pull
request.

## Source vs generated model

DevFlows is source-of-truth driven. Every promoted workflow is defined by files
under `workflows/<workflow-id>/`:

- `workflow.yaml` — the workflow-specific interface and steps
- `devflow.yaml` — metadata (IO channels, docs, scenarios, release config)
- `scripts/` — support scripts

`devflows sync` expands those sources into the consumer-facing copies in
`.github/workflows/`, injecting the shared checkout / artifact / writeback IO
channels. **Never edit `.github/workflows/<id>.yaml` (or its `.github/workflows/<id>/`
support scripts) directly** — your change will be overwritten and CI will fail
the drift check.

After changing any source, regenerate and commit the outputs together:

```bash
devflows sync          # regenerate .github/workflows/
devflows docs          # regenerate reference documentation
devflows test-generate # regenerate scenario workflows
```

`pixi run lint` runs the `--check` form of each generator and fails if the
committed outputs are stale.

## Conventional commits (required)

DevFlows uses [Conventional Commits](https://www.conventionalcommits.org/).
This is **required**: release-please derives each workflow's version and
changelog from commit messages, so an incorrectly typed or scoped commit
produces a wrong (or missing) release.

Use a workflow ID as the scope for changes to that workflow's behavior:

```text
feat(pandoc): add working-directory scenario coverage
fix(writeback): stage only paths that exist after mutation
docs(build-devcontainer): document the merge job permissions
test(pandoc): add hosted artifact assertions
```

- `feat(<id>):` — a new capability for workflow `<id>` (minor bump)
- `fix(<id>):` — a bug fix for workflow `<id>` (patch bump)
- `feat(<id>)!:` or a `BREAKING CHANGE:` footer — a breaking change (major bump)
- `docs`, `test`, `chore`, `refactor` — non-releasing changes

Changes to shared tooling (not tied to one workflow) use scopes such as `cli`,
`docs`, `test`, or `release`. Each active workflow must have a matching
release-please package entry; `pixi run release-dry-run` validates this.

## Pull requests

- Use a Conventional Commits-style PR title.
- Regenerate and commit outputs (`devflows sync`, `docs`, `test-generate`).
- Add or update tests and documentation for behavior changes.
- Ensure `pixi run lint` and `pixi run test` pass.

## Promoting a workflow

Turning a draft or new idea into a versioned, documented, tested workflow
follows the promotion checklist in
[docs/dev-guide/workflow-lifecycle.md](docs/dev-guide/workflow-lifecycle.md).
Start there before moving anything out of `workflows/_drafts/`.
