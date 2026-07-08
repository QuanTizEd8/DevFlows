# Developer Troubleshooting

This page covers common maintainer problems.

## `lint` Reports Generated Files Are Stale

Run the relevant generator:

```bash
pixi run devflows sync
pixi run devflows docs
pixi run devflows test-generate
```

Then rerun:

```bash
pixi run lint
```

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
- inspect the generated `.github/workflows/devflows-local-scenarios.yaml`

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
pixi run release-dry-run
```

Then compare active workflow IDs with the package entries in:

- `.github/release-please/config.json`
- `.github/release-please/manifest.json`

Every active workflow needs a matching release-please package.
