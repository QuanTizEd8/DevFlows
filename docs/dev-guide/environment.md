# Development Environment

DevFlows uses Pixi for reproducible project tooling. The devcontainer is the
recommended development environment because it already contains the expected
system tools and Docker access for local workflow tests.

## Tooling Layers

- **Pixi** provides every project tool: ruff, shellcheck, shfmt, actionlint,
  zizmor, taplo, yamllint, prettier, lefthook, pytest, Sphinx, release-please,
  and the Python package dependencies. A contributor with only `pixi` and `task`
  installed can run everything here except the Docker/`act`-dependent scenarios.
- **The devcontainer** installs infrastructure only: pixi, `task` (go-task),
  `act`, Docker, and shell/CLI niceties, plus `gitleaks` (the one lint tool that
  has no conda-forge or PyPI package). Project tools come from Pixi, not
  features.
- **Taskfile** is the single task registry. Every task delegates to a
  pixi-provided tool via `pixi run -- <tool>`; `task` itself stays outside Pixi
  (install it from the devcontainer or with `brew install go-task`).

## Install And Check

Inside the devcontainer (or any machine with `pixi` and `task`):

```bash
pixi install
task lint
task test
```

## Local Scenario Tests

Local scenario tests use `act` and Docker:

```bash
task scenarios-local
```

Local tests are for fast feedback. They should cover paths that can be run
faithfully under `act`. Paths that require GitHub-hosted services, such as newer
artifact upload/download behavior, should be covered by hosted scenario tests.

## When Dependencies Change

If Pixi dependencies change, update both `pixi.toml` and `pixi.lock`. Keep
tooling additions scoped to actual project needs and prefer using existing tools
already present in the Pixi environment.
