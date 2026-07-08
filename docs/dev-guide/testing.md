# Testing

DevFlows uses layered testing. The goal is to catch syntax, metadata, generator,
security, and behavior problems before a workflow is released.

## Test Layers

Static checks : `pixi run lint` validates metadata, generated-file drift, GitHub
Actions syntax, formatting, shell scripts, and security findings.

Unit tests : `pixi run test` runs Python tests for catalog loading, docs
generation, release checks, YAML handling, and scenario generation.

Local scenario tests : `pixi run test-local` generates local scenario workflows
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
        - test/scenarios/pandoc/working-directory/output.html
      inputs:
        checkout-enabled: false
        pandoc-image: pandoc/core:3.8
        pandoc-working-directory: test/scenarios/pandoc/working-directory
        pandoc-arguments: >-
          --standalone --output=output.html input.md
      assertions:
        - type: file-exists
          path: test/scenarios/pandoc/working-directory/output.html
```

`id` : Stable scenario identifier. Use lowercase letters, numbers, and hyphens.

`runs` : Where the scenario should run. Supported values are `local` and
`hosted`.

`inputs` : Inputs passed to the reusable workflow call.

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

## Local And Hosted Split

Use local scenarios for fast behavior checks that `act` can run faithfully. Use
hosted scenarios for GitHub service behavior, including artifact upload/download
and any path that depends on hosted runner semantics.

Do not add local-runner branches to production reusable workflows. If `act`
cannot emulate a hosted service, keep that scenario hosted-only.

## Generated Test Workflows

Generate scenario workflows with:

```bash
pixi run devflows test-generate
```

Generated files:

- `.github/workflows/devflows-local-scenarios.yaml`
- `.github/workflows/devflows-scenarios.yaml`

The lint task checks that these files are current:

```bash
pixi run devflows test-generate --check
```

## Adding A Scenario

1. Add or update fixtures under `test/scenarios/<workflow-id>/`.
2. Add a scenario under `tests.scenarios`.
3. Include at least one assertion.
4. Use `local` for fast paths and `hosted` for GitHub service paths.
5. Run `pixi run devflows test-generate`.
6. Run `pixi run test-local` for local scenarios.
7. Let hosted CI run hosted scenarios after the branch is pushed.
