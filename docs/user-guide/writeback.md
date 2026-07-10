# Using The Writeback Workflow

The Writeback workflow commits a validated payload artifact to a repository
branch. It is the shared write channel used by DevFlows workflows that can write
generated files back to a repository.

## When To Use It

Use Writeback when repository state is the intended output, such as generated
documentation, lock files, or checked-in reports. Use normal artifact upload
when the output only needs to be inspected by CI or downloaded from a workflow
run.

The caller must grant `contents: write` or pass a token with equivalent access:

```yaml
permissions:
  actions: read
  contents: write
```

## Payload Format

Writeback consumes an artifact containing:

- `manifest.json`
- `files/<relative-path>` for each file to write

The manifest records the file list, SHA-256 digests, executable bits, directory
replacement paths, and explicit deletions. The workflow validates the manifest
and file hashes before copying anything into the target checkout.

Directory paths are replacement paths. If a payload declares `docs/generated`,
the target `docs/generated` directory is removed before payload files are
copied, so deleted generated files are staged correctly.

## Direct Calls

Most users will call a higher-level workflow such as Pandoc and let it create
the payload. Direct calls are useful when a caller job has already uploaded a
valid writeback payload artifact:

```yaml
jobs:
  writeback:
    uses: QuanTizEd8/DevFlows/.github/workflows/writeback.yaml@writeback/v1
    permissions:
      actions: read
      contents: write
    with:
      writeback-artifact-name: generated-files-writeback
      commit-branch: main
      commit-message: "docs: update generated files"
```

Set `commit-expected-base-sha` when the writeback should fail if the target
branch has moved since generation.

## Higher-Level Workflows

The Pandoc workflow exposes `commit-*` inputs and calls Writeback internally.
That keeps Pandoc's conversion job read-only while centralizing write behavior
in one reusable workflow.
