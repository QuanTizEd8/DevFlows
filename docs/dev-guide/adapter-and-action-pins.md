# Adapter Model And Action Pins

DevFlows workflows share a uniform interface for the mechanical concerns every
workflow has in common — checking out a repository, downloading input artifacts,
uploading output artifacts, and committing generated files back. Rather than
copy those inputs and steps into each `workflow.yaml`, a workflow declares which
channels it wants and the generator _adapts_ its narrow domain workflow into the
full public one. This page describes that adapter and the pinned-action registry
it draws on.

## The Adapter (IO Channels)

A source `workflows/<id>/workflow.yaml` describes only the workflow-specific
interface. Its `devflow.yaml` `io` block opts into the shared channels:

```yaml
io:
  job: dist # the runner job that receives the injected channel steps
  runtime: true # materialize inlined scripts for this job
  checkout: true # checkout-* inputs/secrets + a pinned checkout step
  artifact-download: true # artifact-download-* inputs + a pinned download step
  artifact-upload: true # artifact-upload-* inputs + a pinned upload step
  writeback: true # commit-* inputs + a nested writeback job
  checkout-jobs: [cibw, conda] # extra jobs that also need the checkout step
  artifact-download-jobs: [conda]
  runtime-jobs: [validate, cibw, conda, collect]
```

At `devflows sync`, the generator (`.dev/src/devflows/publish.py`) expands the
public `.github/workflows/<id>.yaml`: it adds each enabled channel's public
inputs, secrets, and steps, injects them into `io.job` (and any extra `*-jobs`),
inlines the referenced runtime scripts, and appends the nested `writeback` job
when `writeback` is enabled. The channel step for each concern is built from the
**same pinned action** for every workflow (`actions/checkout`,
`actions/download-artifact`, `actions/upload-artifact`), which is what makes the
channels uniform and independently auditable.

The adapter also owns per-job **permissions**. GitHub job-level permission
blocks _replace_ the workflow-level grant rather than merge with it, so when the
generator injects a channel step into a job it grants that job the scope the
channel needs (`contents: read` for checkout, `actions: read` for
artifact-download/upload/writeback), seeding the existing workflow-level grants
first so none are dropped. The union of every job's permissions is what callers
must grant; it is computed by `caller_required_permissions` and rendered in each
workflow's generated reference page (see {doc}`documentation`). The channel
inputs, secrets, and the runtime/script model are documented in {doc}`metadata`
and {doc}`workflow-lifecycle`.

## Per-Job Script Slicing

`io.runtime` injects the "Materialize DevFlows runtime scripts" step that writes
a job's scripts into `$RUNNER_TEMP/devflows` at run time. The materialize step
inlines **only** the scripts that job references via
`${DEVFLOWS_SCRIPT_ROOT}/…`, including modules named in
`# imports ${DEVFLOWS_SCRIPT_ROOT}/<id>/<mod>.py` comment lines. A workflow can
therefore split a large behavior into focused modules (see
`anaconda-publish/scripts/`) so each job carries only the slice it needs,
keeping the generated file under the size cap.

## The Pin Registry (`ACTION_PINS`)

`.dev/src/devflows/actions.py` holds `ACTION_PINS`, the **single source of
truth** for every third-party action SHA the generator emits or that appears in
the source workflows. Each entry is an `ActionPin(action, sha, version)`:

```python
"checkout": ActionPin(
    "actions/checkout",
    "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "v7.0.0",
),
```

Both `publish.py` (channel steps) and `scenarios.py` (generated scenario
workflows) read this registry, so a SHA is defined exactly once. Helpers:

- `pin(name)` / `ref(name)` — look up an `ActionPin` or its `action@sha` ref.
- `PINS_BY_REF` — reverse map from `action@sha` to `ActionPin`.
- `annotate_pins(text)` — because PyYAML strips comments, this re-appends a
  `# <version>` comment to every `uses: <action>@<sha>` line in the dumped YAML.
  It is block-scalar aware, so a `uses:` line that appears _inside_ an inlined
  heredoc script body is left untouched.

Actions specific to one workflow (for example `cibuildwheel`,
`rattler-build-action`, `gh-action-pypi-publish`) are still registered here so
their version comments are annotated and the contract test covers them.

## The Adapter Contract Test

`tests/package/test_contract.py` is the guard that the generator's assumptions
about each pinned action still hold. For every pinned action the generator emits
a `with:` block for, it fetches that action's `action.yml` at the pinned SHA and
asserts every emitted input key really exists in the action's declared inputs.
It is a network test (marked `network`), excluded from `task test`, and run via:

```bash
task test-contract   # pixi run -- pytest -c .config/pytest.ini -m network tests/package/test_contract.py
```

CI's **Adapter contract** job runs it automatically on any pull request that
touches `.dev/src/devflows/actions.py`, a `workflows/*/workflow.yaml`, or a
`.github/workflows/*.yaml` — so a pin bump that renames or drops an input the
generator relies on fails before it ships. See {doc}`ci`.

## Adding Or Bumping A Pinned Action

1. Add or edit the `ActionPin` entry in `.dev/src/devflows/actions.py`
   (repository, the full 40-character commit SHA, and the human-readable
   `v<version>`). Keep the SHA and version in lockstep — the version is only a
   readable comment for consumers auditing the bare SHA.
2. If a channel step needs a new or changed `with:` key, update the step builder
   in `publish.py` (for example `_checkout_step`, `_download_artifact_step`).
3. Regenerate: `task sync` (and `task test-generate` if scenarios use the pin).
   `task lint`'s drift check fails if you skip this.
4. Run `task test-contract` to confirm every emitted `with:` key still exists on
   the new SHA.
5. If the bump changed a published workflow's output, satisfy the propagation
   guard — land a matching source change so release-please cuts a release (see
   {doc}`release`).

## Renovate Managers

`.config/renovate.json5` keeps every pin current. Two kinds of managers matter
here:

- **`ACTION_PINS` registry** — a custom regex manager matches each
  `ActionPin("<repo>", "<sha>", "v<version>")` and bumps the digest and version
  string together from `github-tags`. It is grouped with the `github-actions`
  manager (which also scans the catalog sources `workflows/*/workflow.yaml`), so
  a source workflow's `uses:` pin, its generated copy, and the registry move in
  one pull request. Run `devflows sync` after merge if any generated copy still
  drifts (the propagation guard flags anything needing a per-workflow release).
- **Pinned tool/container versions** — custom regex managers keep the tool and
  image versions that workflows install or run current, each driven by an inline
  `# renovate: datasource=… depName=…` comment and each backed by a unit test
  that asserts the regex still matches:
  - `anaconda-client` in `anaconda-publish/scripts/commands.py`
  - the `openjournals/inara` container tag in `paper-openjournals/workflow.yaml`
  - `jupyter-repo2docker` in `binder-build/workflow.yaml`
  - `pyyaml` and `requests` in `zenodo-release/workflow.yaml`

Bumps that install a tool version do not change generated output, but a
container-tag or `uses:` pin bump in a source workflow does — run `task sync`
after merge and follow the propagation runbook.
