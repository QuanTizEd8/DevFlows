# CLI Reference

The `devflows` command is the generator and validator behind the catalog. It is
provided by the Pixi environment, so every invocation is
`pixi run -- devflows <subcommand>`; most subcommands also have a one-line
`task` wrapper. This page documents each subcommand and its flags as implemented
in `.dev/src/devflows/cli.py`.

## Invocation

```bash
pixi run -- devflows <subcommand> [options]
```

Every subcommand runs from the catalog root. The CLI locates that root by
walking up from the current directory to the one containing
`.config/project.yaml`, then `chdir`s there before doing any work — so you can
run it from anywhere inside the repository.

On success a subcommand prints a short summary to stderr and exits `0`. A
`DevflowsError` (missing catalog, stale generated files, invalid config) is
printed as `error: <message>` and exits `1`. The `--check` subcommands exit `1`
when they detect drift.

## Global Option

`--root PATH` : Catalog root directory. Accepted by every subcommand. Defaults
to walking up to the directory containing `.config/project.yaml`. Use it to run
the CLI against a catalog checkout that is not an ancestor of your working
directory.

## Subcommands

### `validate`

```bash
pixi run -- devflows validate [--include-drafts]
task validate
```

Loads `.config/project.yaml` (verifying the identity config is present and
well-formed) and every workflow under `workflows/`, then runs the full metadata
check: schema errors, catalog rules (`id` matches the directory, reserved `_`
prefix rejected — `devflows-` too, for back-compat — valid `status`,
`on.workflow_call` present, release config present), IO-channel publish config,
and scenario validation. Prints `validated <n> workflows` on success; prints
each error to stderr and exits `1` otherwise.

`--include-drafts` : Also load workflows from a `workflows/_drafts/` directory.
That directory does not exist today, so the flag is a no-op against the current
catalog; it exists for the optional drafts mechanism described in
{doc}`project-structure`.

### `sync`

```bash
pixi run -- devflows sync [--check]
task sync
```

Regenerates the published reusable workflows `.github/workflows/<id>.yaml` from
each workflow's source (`workflows/<id>/workflow.yaml` plus its metadata,
expanded IO channels, inlined scripts, and pin annotations), and prunes orphaned
published files and leftover script directories. Prints each changed path.

`--check` : Do not write. Exit `1` if any published workflow would change (drift
from the sources), listing the stale paths. This is what `task lint` runs; the
failure message points you to `task sync`. Enforcement of the ASCII-only and
`MAX_GENERATED_WORKFLOW_BYTES = 115_000` constraints happens during rendering,
so an offending source fails `sync` (and `sync --check`) directly.

### `docs`

```bash
pixi run -- devflows docs [--check]
task docs      # runs `devflows docs` then `sphinx-build`
```

Generates the reference pages `docs/reference/catalog.md` and
`docs/reference/workflows/<id>.md` from workflow metadata and interfaces. This
tree is gitignored build output; regenerate it before a Sphinx build.

`--check` : Render the pages to a throwaway temporary directory and fail on any
render error (missing fixture, template failure) without writing. There is no
committed baseline to diff against because `docs/reference/` is ignored, so this
checks that generation _succeeds_, not that committed files match. `task lint`
runs it.

### `test-generate`

```bash
pixi run -- devflows test-generate [--check]
task test-generate
```

Generates the per-workflow scenario workflows from `tests.scenarios` metadata:
`_scenarios-<id>.yaml` (hosted) and, when the workflow declares local scenarios,
`_scenarios-<id>.local.yaml`. Also prunes stale scenario files (a workflow that
loses its scenarios, the pre-rename `devflows-scenarios-<id>.yaml` files, and
the retired monolithic `devflows-scenarios.yaml` /
`devflows-local-scenarios.yaml`) and fails if any generated file exceeds the
byte cap.

`--check` : Exit `1` if any generated scenario file would change, listing the
stale paths. `task lint` runs it.

### `test-local`

```bash
pixi run -- devflows test-local
task scenarios-local   # aliases: task test-local, task test:local
```

Generates the local scenario workflows and runs them through `act`. Requires
Docker and `act` (available in the devcontainer). Use it for fast feedback on
paths `act` can run faithfully; keep hosted-only behavior in hosted scenarios.

### `release-check`

```bash
pixi run -- devflows release-check
task release-check   # aliases: task release:dry-run, task release-dry-run
```

Validates the release-please configuration against the active catalog:
`tag-separator` is `/`, the configured packages and manifest entries exactly
match `workflows/<id>`, each package's `component`/`package-name`/`release-type`
match the workflow, and each `devflow.yaml` `release.major` equals the major
component of its manifest version. Prints `Release configuration is valid.` or
lists every mismatch and exits `1`. See {doc}`release`.

### `propagation-check`

```bash
pixi run -- devflows propagation-check [--base REF]
task propagation-check
DEVFLOWS_BASE_SHA=<ref> task propagation-check   # local run against a base ref
```

Guards against a shared-generator change that alters a published
`.github/workflows/<id>.yaml` without any change under `workflows/<id>/` that
release-please could attribute a release to. Diffs the working tree against a
base ref and exits `1` with a per-workflow message on a violation.

`--base REF` : Base git ref to diff against. Defaults to the `DEVFLOWS_BASE_SHA`
environment variable. When neither is set the check prints a skip notice and
exits `0`, so it is a no-op locally unless you opt in. CI sets
`DEVFLOWS_BASE_SHA` to the pull request base. The runbook is in {doc}`release`.

### `list`

```bash
pixi run -- devflows list
```

Prints one active workflow ID per line to stdout, then `listed <n> workflows` to
stderr. Handy for scripting over the catalog. No `task` wrapper.

## The `--check` Family And `task lint`

The three `--check` subcommands (`sync --check`, `docs --check`,
`test-generate --check`) plus `validate` are exactly what `task lint`'s
`lint:generator` step runs, so a normal `task lint` proves metadata is valid and
no committed generated file has drifted. When it fails, the fix is to run the
matching writer (`task sync` / `task docs` / `task test-generate`) and commit
the result.
