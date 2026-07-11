# Testing

DevFlows uses layered testing. The goal is to catch syntax, metadata, generator,
security, and behavior problems before a workflow is released.

## Test Layers

Static checks : `task lint` validates metadata, generated-file drift, GitHub
Actions syntax, formatting, shell scripts, and security findings.

Unit tests : `task test` runs Python tests for catalog loading, docs generation,
release checks, YAML handling, and scenario generation.

Local scenario tests : `task scenarios-local` generates local scenario workflows
and runs them with `act`.

Hosted scenario tests : one `.github/workflows/devflows-scenarios-<id>.yaml`
file per catalog workflow runs scenarios that require real GitHub-hosted
behavior, including artifact upload/download. The suite is split per workflow so
no single generated file crosses the size GitHub startup-rejects; GitHub runs
the separate files in parallel on the same event, so total coverage is
unchanged.

## Scenario Fields

Each scenario lives in `tests.scenarios` in `devflow.yaml`.

```yaml
tests:
  scenarios:
    - id: working-directory-local
      name: Working directory conversion without artifact upload
      runs:
        - local
      cleanup:
        - tests/scenarios/pandoc/working-directory/output.html
      inputs:
        checkout-enabled: false
        pandoc-image: pandoc/core:3.8
        pandoc-working-directory: tests/scenarios/pandoc/working-directory
        pandoc-arguments: >-
          --standalone --output=output.html input.md
      assertions:
        - type: file-exists
          path: tests/scenarios/pandoc/working-directory/output.html
```

`id` : Stable scenario identifier. Use lowercase letters, numbers, and hyphens.

`runs` : Where the scenario should run. Supported values are `local` and
`hosted`.

`inputs` : Inputs passed to the reusable workflow call.

`expect` : Expected outcome of the scenario. `success` (the default) calls the
reusable workflow and asserts it succeeded. `validation-failure` is a
negative-path scenario that runs the workflow's input-validation script directly
instead of calling it; see
[Validation-Failure Scenarios](#validation-failure-scenarios).

`failure-message-contains` : Only with `expect: validation-failure`. Requires
the rejected validation script's output to contain this substring, so a scenario
can pin the specific rejection message.

`cleanup` : Local files or directories removed before a local scenario runs.

`artifact` : Hosted artifact metadata used when hosted assertions need to
inspect files produced by the reusable workflow job.

`setup-artifact` : Hosted setup artifact metadata. The generated setup job
writes declared files and uploads them before the reusable workflow call. Use
this to test workflows that consume artifacts through `artifact-download-*`
inputs.

`mutation` : Hosted mutation metadata for scenarios that intentionally write to
GitHub state. The first supported mutation is `type: ephemeral-branch`, which
creates a unique branch for the workflow run and deletes it in an `always()`
cleanup job.

`writeback-payload` : Payload metadata for Writeback scenarios. The generated
setup job creates initial branch state, writes the payload files, uploads the
payload artifact, calls the Writeback reusable workflow, asserts the branch
state, and deletes the branch.

`assertions` : Post-run checks that must pass.

## Supported Assertions

`workflow-output-equals` : Compares a reusable workflow output to an expected
string.

`file-exists` : Fails unless a file exists at the exact `path`.

`file-glob-exists` : Fails unless at least one file matches the shell glob in
`path` (`*`, `?`, `**` with `recursive`). Use this when the producer emits a
non-deterministic filename — for example a cibuildwheel/auditwheel wheel, whose
platform tag lists every manylinux compatibility level it satisfies, so the
exact name is not stable (`pkg-0.1.0-cp313-cp313-*manylinux*.whl`).

`file-contains` : Fails unless a file exists and contains a string.

Hosted file assertions require artifact metadata because reusable workflow calls
run as separate jobs. The generated hosted assertion job downloads the artifact
before inspecting files.

Hosted artifact input scenarios can declare setup files:

```yaml
setup-artifact:
  name: pandoc-input-markdown
  path: .devflows-test/pandoc/artifact-download/source.md
  files:
    - path: .devflows-test/pandoc/artifact-download/source.md
      content: |
        # Pandoc Artifact Input
```

The generated setup job uploads that artifact, the reusable workflow downloads
it through its normal artifact-download inputs, and assertion jobs inspect the
workflow's output artifact.

Each `files[*]` entry supplies its bytes with exactly one of three keys:

- `content` : inline UTF-8 text.
- `source-path` : a workspace-relative path (no `..`) of a file already in the
  checkout, copied verbatim. Use this for binary or large payloads such as a
  prebuilt wheel that a fixture commits under `tests/scenarios/<workflow-id>/`.
- `content-base64` : base64-encoded bytes decoded at setup time. Use this for a
  small inline binary payload.

```yaml
setup-artifact:
  name: python-test-wheelhouse
  path: .devflows-test/python-test/wheelhouse
  files:
    - path: .devflows-test/python-test/wheelhouse/example-1.0-py3-none-any.whl
      source-path: tests/scenarios/python-test/fixtures/example-1.0-py3-none-any.whl
```

Both `source-path` and the destination `path` are validated to stay inside the
workspace (absolute paths, `..`, and internal workflow directories are
rejected).

Hosted writeback scenarios can declare ephemeral branch mutation:

```yaml
mutation:
  type: ephemeral-branch
  branch-prefix: devflows/e2e/writeback
  fixture-path: .devflows-e2e/writeback
  initial-files:
    - path: generated/stale.html
      content: stale
writeback-payload:
  artifact-name: writeback-e2e-payload
  paths:
    - generated
  delete-paths:
    - remove.html
  files:
    - path: generated/index.html
      content: |
        <h1>Updated by writeback</h1>
```

Mutation scenarios are skipped on `pull_request` events. They run on trusted
`push` and `workflow_dispatch` events, where the generated setup, writeback, and
cleanup jobs can request `contents: write`.

(validation-failure-scenarios)=

## Validation-Failure Scenarios

Set `expect: validation-failure` to assert that a workflow **rejects bad
inputs** — for example, that its validate step refuses an empty build matrix or
a nothing-to-build call.

This is deliberately honest about what it exercises. GitHub does **not** support
`continue-on-error` on a `uses:` (reusable-workflow call) job, and actionlint
rejects it, so we cannot let a real reusable call fail and keep the run green.
Instead, a validation-failure scenario does **not** call the reusable workflow
at all. The generated job:

1. Checks the repository out (pinned, `persist-credentials: false`) on hosted
   runners; local (`act`) runs use the bind-mounted workspace.
2. Runs the target workflow's `validate-inputs.py` directly, with the exact
   `env` its own validate step declares — reconstructed by substituting the
   scenario's `inputs` (and the workflow input defaults for anything unset) into
   the step's `${{ inputs.* }}` expressions.
3. Asserts the script exits **nonzero**. The run stays green when validation
   fails as designed; the job fails (with a clear message) if the script
   unexpectedly accepts the inputs, or if `failure-message-contains` is set but
   absent from the captured output.

```yaml
tests:
  scenarios:
    - id: nothing-to-build
      name: All build flavors disabled fails validation
      runs:
        - local
        - hosted
      expect: validation-failure
      failure-message-contains: "at least one build flavor"
      inputs:
        sdist-enabled: false
        wheel-enabled: false
```

This tests the input-validation **script layer** in CI. It does not exercise a
full reusable-call failure end to end — that is a future capability that needs a
throwaway sandbox repository to call into. Because a validation-failure job is a
plain checkout-and-run job, it runs faithfully under `act`, so it supports both
`local` and `hosted` runs.

Constraints (enforced by `devflows validate`):

- The target workflow must expose a **discoverable validate step**: a step whose
  `run` invokes `${DEVFLOWS_SCRIPT_ROOT}/<id>/validate-inputs.py`
  (conventionally in a job named `validate`).
- That step's `env` values may only reference `inputs.*` expressions. Any
  `github.*`, `steps.*`, `secrets.*`, `matrix.*`, `needs.*`, or compound
  expression is rejected, because the harness must reconstruct the env from the
  scenario inputs alone — substitution has to be total. (The one exception is
  the generator-injected `DEVFLOWS_SCRIPT_ROOT` runtime var, which is dropped:
  the harness invokes the script by its checkout path.)
- They declare **no** `assertions`, `artifact`, `setup-artifact`, `mutation`,
  `writeback-payload`, or `cleanup`: the only check is that validation rejected
  the inputs.
- Boolean and number inputs are serialized the way GitHub presents them to an
  expression (`true`/`false`, decimal strings), consistent with how the success
  path feeds the same typed inputs to the call job's `with:` block.

Because the validate scripts are extracted, lint-covered `.py` files, you can
also assert their specific messages with plain unit tests of the script; the
scenario proves the same rejection fires with the workflow's real input wiring.

> **Adopting this in a workflow.** Give the workflow a `validate` job whose step
> runs `${DEVFLOWS_SCRIPT_ROOT}/<id>/validate-inputs.py` and whose `env` maps
> only `inputs.*` values (plus the injected `DEVFLOWS_SCRIPT_ROOT`). Then add a
> scenario with `expect: validation-failure` and inputs that trip a specific
> rejection, optionally pinning it with `failure-message-contains`.

## Local And Hosted Split

Use local scenarios for fast behavior checks that `act` can run faithfully. Use
hosted scenarios for GitHub service behavior, including artifact upload/download
and any path that depends on hosted runner semantics.

Do not add local-runner branches to production reusable workflows. If `act`
cannot emulate a hosted service, keep that scenario hosted-only.

## Generated Test Workflows

Generate scenario workflows with:

```bash
pixi run -- devflows test-generate
```

Generated files (one hosted and one local file per catalog workflow that owns
scenarios; a local file is emitted only when the workflow has local scenarios):

- `.github/workflows/devflows-scenarios-<id>.yaml` — hosted scenarios
- `.github/workflows/devflows-scenarios-<id>.local.yaml` — local (`act`)
  scenarios

`test-generate` also prunes stale scenario files (a workflow that loses its
scenarios, or the retired monolithic `devflows-scenarios.yaml` /
`devflows-local-scenarios.yaml`), and fails if any generated file exceeds the
byte cap GitHub startup-rejects. The lint task checks that these files are
current:

```bash
pixi run -- devflows test-generate --check
```

## Adding A Scenario

1. Add or update fixtures under `tests/scenarios/<workflow-id>/`.
2. Add a scenario under `tests.scenarios`.
3. Include at least one assertion.
4. Use `local` for fast paths and `hosted` for GitHub service paths.
5. Run `pixi run -- devflows test-generate`.
6. Run `task scenarios-local` for local scenarios.
7. Let hosted CI run hosted scenarios after the branch is pushed.
