# Artifacts And Outputs

Reusable workflows communicate with downstream jobs through outputs, artifacts,
or both. This page covers the shared conventions: workflow outputs and how to
chain them, the dist-manifest integrity contract the Python tier adds on top of
artifacts, and the GitHub Pages artifact channel.

## Workflow Outputs

Outputs are best for small strings such as generated identifiers, computed
paths, artifact names, versions, or status values. Read them through
`needs.<job_id>.outputs` when a workflow exposes outputs. Not every workflow
exposes outputs; check the generated reference page before depending on one.

## Chain Outputs

DevFlows workflows are designed to compose. A producing job runs one workflow
and a consuming job reads its outputs. The Python tier is the richest example:
`python-build` exposes the artifact names it published, the parsed
`package-version`, and — for integrity-checked chaining — a `dist-manifest`:

| output                                                                 | use                                                                                             |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `sdist-artifact-name` / `wheels-artifact-name` / `conda-artifact-name` | Names of the published artifacts; the empty string when a flavor built nothing.                 |
| `package-version`                                                      | Version parsed from the built files; feed it to a publisher's `publish-expected-version` guard. |
| `dist-manifest`                                                        | Schema-versioned JSON integrity contract consumed by `pypi-publish` and `anaconda-publish`.     |
| `dist-sha256sums`                                                      | Base64 sha256sum lines in the format `slsa-github-generator` expects for provenance subjects.   |

Other tiers follow the same idea: `docs-build` exposes `pages-artifact-name`,
`deploy-pages` exposes `pages-url`, `python-test` exposes
`report-artifact-name`, and `zenodo-release` exposes `zenodo-doi` and
`release-url`.

Two conventions keep chains honest:

- **Guard on non-empty.** An artifact-name, URL, or DOI output is the empty
  string when its flavor produced nothing or its job was skipped (for example a
  dry-run publish). Guard the consuming job so a broken or partial chain fails
  loudly instead of silently no-opping:

  ```yaml
  needs: build
  if: ${{ !cancelled() && needs.build.outputs.sdist-artifact-name != '' }}
  ```

- **Pass the manifest and version through.** Feeding `dist-manifest` and
  `package-version` into a publisher makes tag/artifact skew impossible before
  an irreversible upload.

The full worked chains are in {doc}`getting-started-python` and
{doc}`getting-started-research`.

## Artifacts

Artifacts are best for files and directories. DevFlows workflows use
`artifact-download-*` inputs for artifact input and `artifact-upload-*` inputs
for artifact output. A workflow may upload files when artifact upload is
enabled:

```yaml
with:
  artifact-upload-enabled: true
  artifact-upload-name: docs-html
  artifact-upload-path: output/site
  artifact-upload-if-no-files-found: error
```

A downstream job can download the artifact:

```yaml
permissions:
  # pandoc's published form embeds a writeback commit job requiring these
  # scopes; GitHub validates nested permissions before the run starts, so grant
  # the union even for this read-only upload/download example.
  contents: write
  actions: read

jobs:
  convert:
    # Pin an exact pandoc/vX.Y.Z release tag or a commit SHA.
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=output/readme.html README.md
      artifact-upload-enabled: true
      artifact-upload-name: readme-html
      artifact-upload-path: output/readme.html
      artifact-upload-if-no-files-found: error

  inspect:
    runs-on: ubuntu-latest
    needs: convert
    steps:
      - uses: actions/download-artifact@v8 # pin to a full commit SHA in real usage
        with:
          name: readme-html
          path: downloaded
      - run: test -f downloaded/readme.html
```

## The dist-manifest Integrity Contract

The Python tier hardens artifact handoff with a signed-in-transit integrity
contract. `python-build` emits, next to its named artifacts, a `dist-manifest`
output — a schema-versioned JSON document of every distribution file with its
`sha256`, `size`, and `kind`:

```json
{
  "schema": 1,
  "files": [
    {
      "name": "my_package-1.2.3.tar.gz",
      "sha256": "…",
      "size": 12345,
      "kind": "sdist"
    },
    {
      "name": "my_package-1.2.3-py3-none-any.whl",
      "sha256": "…",
      "size": 23456,
      "kind": "wheel"
    }
  ],
  "artifacts": {
    "sdist": "my-package-sdist",
    "wheels": "my-package-wheels",
    "conda-channel": ""
  }
}
```

`pypi-publish` and `anaconda-publish` take that manifest as an input and upload
**only** files it lists, byte-for-byte `sha256`- and `size`-matched
bidirectionally. Unlisted files, wrong-kind files, digest or size mismatches,
and version skew all fail the run loudly, naming the file. The verification runs
twice — once in a credential-free `verify` job (so the whole ingestion path is
testable in a pull request without any credential) and again atomically inside
the credentialed publish job immediately before upload. The second check is a
TOCTOU guard: `python-build` uploads its artifacts with `overwrite: true`, so an
artifact name is not immutable within a run.

Chain it by passing `python-build`'s output straight through:

```yaml
with:
  publish-dist-manifest: ${{ needs.build.outputs.dist-manifest }}
  publish-expected-version: ${{ needs.build.outputs.package-version }}
```

`zenodo-release` accepts the same manifest optionally (research assets are
heterogeneous — a built distribution has one, a paper PDF does not); when
supplied it verifies the same way, and when omitted assets upload as-is with
their computed `sha256` recorded in the job summary for provenance.

## The GitHub Pages Artifact Channel

Site builders publish through a GitHub Pages artifact rather than the generic
artifact channel, because a plain `upload-artifact` artifact is not
Pages-deployable. `docs-build` uploads the built site as a Pages artifact when
`pages-artifact-enabled: true` (needing no extra permissions) and exposes its
name as `pages-artifact-name`; `deploy-pages` deploys that artifact by name and
exposes the live site as `pages-url`:

```yaml
jobs:
  build-docs:
    uses: QuanTizEd8/DevFlows/.github/workflows/docs-build.yaml@docs-build/vX.Y.Z
    with:
      docs-environment: pip
      pip-install-targets: |
        sphinx
      pages-artifact-enabled: true

  deploy-docs:
    needs: build-docs
    permissions:
      contents: read
      actions: read
      pages: write
      id-token: write
    uses: QuanTizEd8/DevFlows/.github/workflows/deploy-pages.yaml@deploy-pages/vX.Y.Z
    with:
      pages-artifact-name: ${{ needs.build-docs.outputs.pages-artifact-name }}
      pages-artifact-enabled: false
      checkout-enabled: false
```

The default artifact name on both is `github-pages`, so the chain works with no
extra wiring; the elevated Pages permissions (`pages: write`, `id-token: write`)
live only on the deploy job. The full walkthrough is in
{doc}`getting-started-docs-pages`.

## Choosing Between Outputs And Artifacts

Use outputs for values that fit cleanly in workflow expressions. Use artifacts
for generated files, reports, archives, build products, and anything that needs
to be inspected or consumed by a later job.

## Artifact Input

When a workflow supports artifact download, enable it explicitly and name the
artifact or pattern to download:

```yaml
with:
  artifact-download-enabled: true
  artifact-download-name: prepared-sources
  artifact-download-path: input
```

The download runs before the workflow's main tool. Use this when one reusable
workflow consumes files produced by an earlier job. When chaining from
`python-build`, feed the artifact name from its output and point
`artifact-download-path` at the same directory the consumer scans (for example
`test-dist-path` or `publish-dist-path`). A directory with no distributions is a
hard error, so a broken chain fails loudly.

## Commit Writeback

Some workflows can also commit selected generated files back to a branch. This
is opt-in and should only be used when repository state is the intended output.
DevFlows routes these commits through a shared writeback channel; see the
generated {doc}`Writeback reference </reference/workflows/writeback>`:

```yaml
permissions:
  # The nested writeback commit job requires both scopes; validated before the run.
  contents: write
  actions: read

jobs:
  convert:
    # Pin an exact pandoc/vX.Y.Z release tag or a commit SHA.
    uses: QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z
    with:
      pandoc-image: pandoc/core:3.8
      pandoc-arguments: >-
        --standalone --output=docs/readme.html README.md
      commit-enabled: true
      commit-paths: docs/readme.html
      commit-message: "docs: update generated readme"
```

The caller must grant `contents: write` or pass a write-capable commit token.
Use artifact upload for reviewable CI outputs; use commit writeback when the
generated file should become part of the repository.

## Common Artifact Problems

- If an artifact path is relative, it is relative to the workspace used by the
  job running the reusable workflow.
- Set `artifact-upload-if-no-files-found: error` when missing output should fail
  CI.
- Be explicit about artifact names so downstream jobs download the correct
  files, and pass distinct names when invoking the same workflow more than once
  in a run (artifact names are immutable per run).
- A digest mismatch during a manifest-verified publish fails the run by design;
  see {doc}`troubleshooting`.
- Local `act` runs are useful for conversion checks, but hosted GitHub runners
  are the reliable place to test artifact upload/download behavior.
