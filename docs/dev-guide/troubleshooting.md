# Developer Troubleshooting

This page covers common maintainer problems.

## `lint` Reports Generated Files Are Stale

Run the relevant generator:

```bash
pixi run -- devflows sync
pixi run -- devflows docs
pixi run -- devflows test-generate
```

Then rerun:

```bash
task lint
```

## `sync` Fails: Non-ASCII Inlined Script

`devflows sync` (and `test-generate`) reject an inlined runtime script that
contains a non-ASCII character, printing
`<file>:<line>: inlined runtime script contains a non-ASCII character`. Inlined
scripts must be ASCII so they render as YAML block literals — a single non-ASCII
byte collapses the whole materialize `run:` block into an escaped scalar that
GitHub rejects at startup. Edit the named line to use ASCII (for example replace
an em-dash `—` with `--`, or curly quotes with straight quotes), then re-run the
generator.

## `sync` Fails: Generated Workflow Over The Size Cap

Generation fails with
`generated workflow is <N> bytes, over the 115000-byte cap` when a published or
scenario workflow exceeds `MAX_GENERATED_WORKFLOW_BYTES`. GitHub startup-rejects
oversized workflows with an opaque "workflow file issue" that no linter catches,
so the cap is enforced locally. Reduce the inlined footprint rather than raising
the cap: split a shared script module so each job inlines only the slice it
references, move a large scenario into its own workflow, or trim an oversized
fixture. See {doc}`workflow-lifecycle` and {doc}`testing`.

## `propagation-check` Fails

A published `.github/workflows/<id>.yaml` changed but nothing under
`workflows/<id>/` did — usually after a shared-generator or action-pin bump.
Land a real source change under that workflow's package path (so release-please
can attribute a release to it) in the same pull request, or revert the
regenerated output if the diff is genuinely consumer-neutral. The runbook is in
{doc}`release`.

## `actionlint` Fails Generated Workflows

Check the source generator or workflow metadata first. Generated workflow files
should not be hand-edited. If a reusable workflow call fails validation, confirm
that the called workflow exposes the inputs and secrets used by the scenario.

## `yamllint` Fails Generated Workflows

Generated YAML should be emitted by `devflows.yaml.dump_yaml`. If style issues
appear in generated files, fix the dumper or renderer instead of formatting the
generated file manually.

## Local Scenario Tests Fail Under `act`

First determine whether the scenario depends on a hosted GitHub service. If it
does, make it hosted-only. Keep production workflow logic free of `act`-specific
branches.

If the scenario should work locally:

- confirm Docker is available
- confirm the scenario uses `checkout-enabled: false` when it relies on the
  bind-mounted local workspace
- confirm `cleanup` removes outputs from previous runs
- inspect the generated `.github/workflows/_scenarios-<id>.local.yaml` for the
  workflow under test

## Hosted Scenario Assertions Cannot Find Files

Hosted assertion jobs run separately from reusable workflow jobs. File
assertions need artifact handoff:

```yaml
artifact:
  name: my-artifact
  path: .devflows-test-artifacts/my-scenario
```

The reusable workflow inputs must upload the same artifact name, usually with
`artifact-upload-enabled: true` and `artifact-upload-name: <name>`.

## Release Validation Fails

Run:

```bash
task release-check
```

Then compare active workflow IDs with the package entries in:

- `.github/release-please/config.json`
- `.github/release-please/manifest.json`

Every active workflow needs a matching release-please package.
