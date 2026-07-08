# Development Environment

DevFlows uses Pixi for reproducible project tooling. The devcontainer is the
recommended development environment because it already contains the expected
system tools and Docker access for local workflow tests.

## Tooling Layers

- Pixi provides Python, pytest, Sphinx, actionlint, yamllint, prettier, taplo,
  release-please, and Python package dependencies.
- The devcontainer provides system-level tools such as Docker access and shell
  tooling used by local checks.
- Taskfile provides short command aliases for common workflows.

## Install And Check

Inside the devcontainer:

```bash
pixi install
pixi run lint
pixi run test
```

To use Taskfile aliases:

```bash
task lint
task test
task docs
```

## Local Scenario Tests

Local scenario tests use `act` and Docker:

```bash
pixi run test-local
```

Local tests are for fast feedback. They should cover paths that can be run
faithfully under `act`. Paths that require GitHub-hosted services, such as newer
artifact upload/download behavior, should be covered by hosted scenario tests.

## When Dependencies Change

If Pixi dependencies change, update both `pixi.toml` and `pixi.lock`. Keep
tooling additions scoped to actual project needs and prefer using existing tools
already present in the Pixi environment.
