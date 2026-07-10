# Calling Reusable Workflows

Reusable workflows are called at the job level with `jobs.<job_id>.uses`. They
are not called as a step. That means the reusable workflow owns the runner, job
steps, and job-level behavior for that call.

## Basic Call Shape

```yaml
name: Build documents

on:
  pull_request:
  push:
    branches:
      - main

permissions:
  contents: read

jobs:
  pandoc:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v1
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=output/readme.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: readme-html
      artifact-upload-path: output/readme.html
```

Every workflow has its own generated reference page under the
{doc}`workflow catalog </reference/catalog>`. Use that page to find:

- supported inputs and defaults
- required and optional secrets
- outputs
- declared permissions
- examples
- test scenarios maintained by DevFlows

## Standard IO Channels

Promoted DevFlows workflows should use a consistent shape for file movement:

- checkout inputs bring repository content into the workflow workspace
- `artifact-download-*` inputs bring previously produced files into the
  workspace before the main tool runs
- `artifact-upload-*` inputs publish generated files as workflow artifacts
- `commit-*` inputs optionally write selected generated files back to a
  repository branch

The Pandoc workflow follows this model. Workflows may document additional
channels when the underlying tool needs them, but callers should expect these
names to be consistent across promoted workflows.

## Inputs

Inputs are passed through the `with` block. Boolean and number inputs can be
written as native YAML values:

```yaml
with:
  checkout-fetch-depth: 0
  checkout-lfs: true
```

For long strings, prefer YAML block scalars. They make command-oriented inputs
easier to read and review:

```yaml
with:
  pandoc-arguments: >-
    --standalone --metadata=title:"Project Report" --output=dist/report.html
    docs/report.md
```

## Secrets

Reusable workflow secrets are passed with `secrets`. If a workflow supports a
custom checkout token or SSH key, pass only the secret needed for that caller:

```yaml
jobs:
  pandoc:
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/v1
    secrets:
      checkout-token: ${{ secrets.DEVFLOWS_CHECKOUT_TOKEN }}
```

Do not pass broad repository or organization secrets to workflows that do not
need them. Keep secret names specific to their purpose.

## Outputs

Reusable workflow outputs are read from `needs.<job_id>.outputs` in downstream
jobs. Not every workflow exposes outputs. Check the generated reference page
before depending on one.

## Calling From Pull Requests

Be careful when a caller workflow runs on pull requests from forks. Avoid using
trusted secrets or privileged tokens with untrusted code. If a reusable workflow
checks out code, understand which repository and ref it checks out, and keep the
caller permissions as narrow as possible.

## Local Versus Hosted Behavior

GitHub-hosted runners are the source of truth. Local tools such as `act` are
useful for fast feedback, but they do not emulate every GitHub service. In
particular, artifact upload/download behavior can differ for newer action
versions. DevFlows keeps hosted scenario tests for paths that require GitHub
services.
