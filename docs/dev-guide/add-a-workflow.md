# Adding A Workflow

This is the end-to-end walkthrough for adding a new reusable workflow to the
catalog and promoting it to a released, documented, tested workflow. It expands
the checklist in {doc}`workflow-lifecycle` into concrete steps. Follow it start
to finish; a workflow is not done until every step passes.

Throughout, replace `<id>` with your workflow's ID (lowercase, hyphenated, and
**not** starting with `devflows-`, which is reserved for internal workflows).
`pandoc` is the simplest model to read; `python-build` models a matrix with
extra channel jobs; the publishing workflows model credentialed jobs (see
{doc}`publishing-conventions`).

## 1. Create The Directory And Source Workflow

```text
workflows/<id>/
  workflow.yaml     # the reusable workflow (domain interface only)
  devflow.yaml      # metadata
  scripts/          # support scripts (optional but usual)
```

`workflow.yaml` describes only the **workflow-specific** interface — do not
hand-author checkout/artifact/writeback inputs or steps; those come from the IO
channels in step 4. Start from `permissions: {}` and grant each job only what it
needs. Pass every untrusted input through an environment variable into a script
(never interpolate `${{ inputs.* }}` into shell text), and pin any third-party
action to a SHA registered in `src/devflows/actions.py` (see
{doc}`adapter-and-action-pins`).

A minimal shape:

```yaml
name: "[Reusable]: My Flow"

on:
  workflow_call:
    inputs:
      my-argument:
        description: What it does.
        type: string
        required: false
        default: ""
    outputs:
      result:
        description: Something downstream can chain on.
        value: ${{ jobs.run.outputs.result }}

permissions: {}

jobs:
  validate:
    name: Validate inputs
    runs-on: ubuntu-latest
    permissions: {}
    steps:
      - name: Validate inputs
        env:
          DEVFLOWS_SCRIPT_ROOT:
            ${{ steps.devflows-runtime.outputs.script-root }}
          MY_ARGUMENT: ${{ inputs.my-argument }}
        shell: bash
        run: python "${DEVFLOWS_SCRIPT_ROOT}/<id>/validate-inputs.py"

  run:
    name: Run
    needs: validate
    runs-on: ubuntu-latest
    outputs:
      result: ${{ steps.run.outputs.result }}
    steps:
      - name: Run
        id: run
        env:
          DEVFLOWS_SCRIPT_ROOT:
            ${{ steps.devflows-runtime.outputs.script-root }}
          MY_ARGUMENT: ${{ inputs.my-argument }}
        shell: bash
        run: python "${DEVFLOWS_SCRIPT_ROOT}/<id>/run.py"
```

`${{ steps.devflows-runtime.outputs.script-root }}` and
`${DEVFLOWS_SCRIPT_ROOT}` refer to the generator-injected materialize step; you
write the reference, `devflows sync` injects the step (step 4). Actionlint
cannot type-check the source in isolation because of that injected step, which
is why it scans the _generated_ workflow — the sync drift check keeps the two
faithful.

## 2. Write The Metadata (`devflow.yaml`)

Required top-level keys are `id`, `name`, `status`, and `release`; unknown keys
are rejected (the schema sets `additionalProperties: false`).

```yaml
id: <id> # must equal the directory name
name: My Flow
summary:
  One or two sentences describing what the workflow does and its safety story.
status: active # active | deprecated | experimental
owners:
  - DevFlows maintainers
release:
  type: simple # must match the release-please package release-type
  major: 0 # current released major line; 0 while pre-1.0
docs:
  category: Utilities # see the taxonomy note below
  keywords:
    - <id>
    - relevant
    - search
    - terms
notes:
  - Any non-obvious behavior, and the exact caller permission union.
```

`docs.category` is a free string in the schema, but by convention use one of the
existing catalog categories so the generated catalog groups your workflow
correctly: **Containers, Documents, Pages, Python, Publishing, Utilities**. If
none fits, raise it with the maintainers rather than inventing a one-off tier.

`release.major` must equal the major component of the release-please manifest
version you add in step 6 (`0` ↔ `0.0.0`); `task release-check` enforces this.

## 3. Write Support Scripts

Keep nontrivial logic in `workflows/<id>/scripts/*.py`, not in YAML. Scripts:

- must be **ASCII** — `devflows sync` rejects a non-ASCII byte in an inlined
  script (it would corrupt the YAML block literal and startup-fail on GitHub).
- read inputs from environment variables the step sets; never trust that a value
  is shell-safe. `shlex`-split and allowlist any pass-through arguments.
- are lint-covered `.py` files (ruff, shellcheck for shell), so they are
  unit-testable on their own.

For a larger workflow, split logic into focused modules that each job imports,
and declare them with `# imports ${DEVFLOWS_SCRIPT_ROOT}/<id>/<module>.py`
comment lines in the job's `run` block. The generator inlines only the modules a
job references, so a shared module is not duplicated into every job and the
generated file stays under the size cap
(`MAX_GENERATED_WORKFLOW_BYTES = 115_000`). `anaconda-publish/scripts/` is the
model.

## 4. Declare IO Channels

Instead of hand-authoring checkout, artifact, or writeback plumbing, opt into
the shared channels in `devflow.yaml`. `devflows sync` then expands the public
workflow with the corresponding inputs, secrets, pinned steps, per-job
permissions, and (for writeback) a nested commit job.

```yaml
io:
  job: run # the runner job that receives the injected steps + materialize step
  runtime: true # inline this job's ${DEVFLOWS_SCRIPT_ROOT} scripts
  checkout: true # add checkout-* inputs/secrets + a pinned checkout step
  artifact-download: true # add artifact-download-* inputs + a pinned download step
  artifact-upload: true # add artifact-upload-* inputs + a pinned upload step
  writeback: true # add commit-* inputs + a nested writeback job (requires runtime)
  # Any additional jobs that also need a channel:
  checkout-jobs: [matrix-leg] # jobs that also need the checkout step
  artifact-download-jobs: [matrix-leg]
  runtime-jobs: [validate, matrix-leg] # every job that runs a ${DEVFLOWS_SCRIPT_ROOT} script
```

Rules the generator enforces (`validate`): every job that references
`${DEVFLOWS_SCRIPT_ROOT}` must be `io.job` or listed in `runtime-jobs`;
`checkout-jobs`/`artifact-download-jobs` require the matching channel enabled;
none of the `*-jobs` may repeat `io.job`; `writeback` requires `runtime`. The
channel inputs and the runtime/script model are detailed in {doc}`metadata` and
{doc}`adapter-and-action-pins`.

The caller permission union grows with the channels you enable (checkout adds
`contents: read`; artifact/writeback add `actions: read`; writeback's nested job
statically needs `contents: write`). Document the full union in `notes` —
callers must grant it because GitHub validates every nested job's permissions at
startup, before any `if:`.

## 5. Add Fixtures And Scenarios

**Examples** are checked-in caller workflows rendered into the reference page:

```yaml
# in devflow.yaml
examples:
  - name: Basic use
    path: tests/fixtures/<id>/basic.yaml
```

Create `tests/fixtures/<id>/basic.yaml` as a realistic, small caller. A test
(`tests/test_example_fixtures.py`) checks every example path resolves.

**Scenarios** are executable tests under `tests.scenarios`. Include at least one
assertion, and add fixture inputs under `tests/scenarios/<id>/` when a scenario
needs them. Cover a fast happy path (`runs: [local]`) and any GitHub-service
behavior (`runs: [hosted]`). Full field/assertion reference is in
{doc}`testing`.

```yaml
tests:
  scenarios:
    - id: basic-local
      name: Basic run without artifact upload
      runs: [local]
      cleanup:
        - .devflows-test/<id>/basic
      inputs:
        checkout-enabled: false
        my-argument: example
      assertions:
        - type: file-exists
          path: .devflows-test/<id>/basic/output.txt
```

**Add at least one negative-path scenario.** A `validate` job whose step runs
`${DEVFLOWS_SCRIPT_ROOT}/<id>/validate-inputs.py` with an `env` that references
only `inputs.*` expressions lets you assert the workflow rejects bad input:

```yaml
- id: rejects-empty
  name: Empty argument fails validation
  runs: [local, hosted]
  expect: validation-failure
  failure-message-contains: "my-argument must not be empty"
  inputs:
    my-argument: ""
```

The harness runs the validate script directly and asserts it exits nonzero (it
does not call the reusable workflow). This is why the validate step's `env` may
only substitute `inputs.*` — see {doc}`testing` for the constraints.

## 6. Register The Workflow

Three registrations must land in the same change, or `task lint` /
`task release-check` will fail:

1. **release-please config** — add a package entry to
   `.github/release-please/config.json`:

   ```json
   "workflows/<id>": {
     "component": "<id>",
     "release-type": "simple",
     "package-name": "<id>",
     "changelog-path": "CHANGELOG.md",
     "initial-version": "0.1.0"
   }
   ```

2. **release-please manifest** — add the baseline version to
   `.github/release-please/manifest.json` (its major must equal
   `release.major`):

   ```json
   "workflows/<id>": "0.0.0"
   ```

3. **catalog test** — add `<id>` in sorted position to the expected list in
   `tests/test_catalog.py::test_catalog_loads_active_workflows`.

If the workflow **pins a tool or container version** (installed with
`uvx --from tool==<version>`, `uv run --with`, or a container image tag), add a
custom Renovate manager in `renovate.json5` driven by an inline
`# renovate: datasource=… depName=…` comment, and a unit test that asserts the
regex still matches the pin (as the existing publishing/paper/binder workflows
do). This keeps the pin auto-updating. See {doc}`adapter-and-action-pins`.

## 7. Generate, Verify, And Promote

Regenerate the committed generated files, then run the full suite:

```bash
task sync            # writes .github/workflows/<id>.yaml
task test-generate   # writes devflows-scenarios-<id>.yaml (+ .local.yaml)
task docs            # regenerates reference pages and builds Sphinx (0 warnings)

task validate
task lint            # includes the --check drift guards and secret scan
task test
task scenarios-local # local act runs (needs docker + act)
task release-check
```

`task lint` fails if you forgot to regenerate — fix with the matching writer and
commit. If your change touched the shared generator (`src/devflows/`), also
satisfy the propagation guard (see {doc}`release`).

### Promotion Checklist

- [ ] `workflow.yaml` declares `permissions: {}` at top level and grants each
      job least privilege; no untrusted input is interpolated into shell text.
- [ ] Third-party actions are SHA-pinned from `ACTION_PINS`.
- [ ] `devflow.yaml` has `id` (= directory), `name`, `summary`,
      `status: active`, `owners`, `release` (major `0`), `docs.category` in the
      taxonomy, and `notes` stating the caller permission union.
- [ ] IO channels declared in `io` rather than hand-authored.
- [ ] Scripts are ASCII and env-mediated; large logic split into per-job
      modules.
- [ ] Examples under `tests/fixtures/<id>/`; scenarios include an assertion and
      a `validation-failure` negative path.
- [ ] Registered in release-please config + manifest + `test_catalog`, and (if
      it pins a tool) in Renovate with a guard test.
- [ ] `task lint`, `task test`, `task scenarios-local`, `task docs` (0
      warnings), and `task release-check` all pass.
