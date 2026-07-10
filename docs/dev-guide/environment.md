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

## Supply-Chain Lock Refresh

The environment has three independently pinned inputs. Renovate
(`renovate.json5`) proposes updates for most of them; the commands below are the
authoritative, offline refresh path and the review guidance.

### Pixi lockfile (`pixi.lock`)

Regenerate it from `pixi.toml` and review the diff:

```bash
task pixi-lock   # runs `pixi lock`
pixi lock --check   # confirms the lockfile is in sync (also runs in nothing-changed CI)
```

Review that only intended packages moved and that no channel or platform was
dropped. Renovate's `pixi` manager and scheduled `lockFileMaintenance` also
refresh this, but that manager is still maturing, so `task pixi-lock` is the
reliable path.

### Devcontainer feature digests (`.devcontainer/devcontainer-lock.json`)

The `ghcr.io/quantized8/devfeats/*` features are referenced without a version
tag and pinned by digest in `devcontainer-lock.json`. Refresh the digests with
the devcontainer CLI (installed via npm, not Pixi):

```bash
npx --yes @devcontainers/cli upgrade --workspace-folder .
```

Review the digest changes against the upstream `devfeats` release notes before
committing. Renovate's `devcontainer` manager proposes feature version bumps,
but the digest lockfile is refreshed with the command above.

### Base image digest and gitleaks (`.devcontainer/Dockerfile`)

The base image is digest-pinned (`FROM ubuntu:26.04@sha256:...`). Re-resolve the
current multi-arch manifest digest and update the `FROM` line:

```bash
docker buildx imagetools inspect ubuntu:26.04 --format '{{ json .Manifest.Digest }}'
```

Renovate's `dockerfile` manager automates this digest bump. `gitleaks` is pinned
by version **and** by per-architecture `sha256` checksums in the same
Dockerfile; because the checksums must change in lockstep with the version, it
is refreshed by hand (bump `GITLEAKS_VERSION` and both `gl_sha` values from the
upstream release checksums), not by Renovate.

After any refresh, rebuild the devcontainer and run `task lint && task test` so
CI parity is preserved.
