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

Hosted scenario tests : `.github/workflows/devflows-scenarios.yaml` runs
scenarios that require real GitHub-hosted behavior, including artifact
upload/download.

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

`expect` : Expected conclusion of the reusable workflow call. `success` (the
default) asserts the call succeeded. `failure` marks a negative-path scenario;
see [Failure-Path Scenarios](#failure-path-scenarios).

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

`file-exists` : Fails unless a file exists.

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

## Failure-Path Scenarios

Set `expect: failure` to assert that a reusable workflow call fails — for
example, that a validate step rejects an empty matrix or a nothing-to-build
call.

```yaml
tests:
  scenarios:
    - id: nothing-to-build
      name: All build flavors disabled fails validation
      runs:
        - hosted
      expect: failure
      inputs:
        checkout-enabled: false
        sdist-enabled: false
        wheel-enabled: false
```

The generated call job runs with `continue-on-error: true`, so the overall run
stays green while the job itself is red; the assert job runs on `!cancelled()`
and requires `needs.<call>.result == 'failure'`. If the call unexpectedly
succeeds, the assert fails and the run goes red.

Constraints:

- `expect: failure` scenarios are **hosted-only**. `act` cannot reliably drive a
  failed reusable-workflow call into a result-asserting job, so listing `local`
  is a validation error.
- They declare **no** `assertions` and no `artifact` metadata: a failed call
  uploads no artifact and produces no outputs, so the only meaningful check is
  the call result, which the assert job makes automatically.

Matching a specific failure **message** is intentionally not supported. The
failure originates in a nested reusable-call job whose logs cannot be reliably
located (the nested-job naming GitHub renders is undocumented) or fetched with
the run's default `actions: read` token while the run is still in progress, so a
log grep would be flaky. Assert specific validate-script messages with unit
tests of the script instead (this is why the validate scripts are extracted,
lint-covered `.py` files).

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

Generated files:

- `.github/workflows/devflows-local-scenarios.yaml`
- `.github/workflows/devflows-scenarios.yaml`

The lint task checks that these files are current:

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
