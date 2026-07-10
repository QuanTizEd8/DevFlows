# Workflow Lifecycle

Promoting a workflow means turning a draft or new idea into a versioned,
documented, tested reusable workflow.

## Lifecycle States

Draft : A workflow under `workflows/_drafts`. Drafts can be incomplete,
inherited, or experimental. They are not part of the public catalog.

Active : A workflow under `workflows/<workflow-id>` with `status: active` in
`devflow.yaml`. Active workflows are synced, documented, tested, and released.

Deprecated : A workflow still present for compatibility but no longer
recommended for new callers.

Experimental : A promoted workflow whose interface is intentionally less stable.
Use this status sparingly and document expectations clearly.

## Promotion Checklist

Before promoting a workflow:

1. Choose a stable workflow ID.
2. Move or create `workflows/<workflow-id>/workflow.yaml`.
3. Add `workflows/<workflow-id>/devflow.yaml`.
4. Define a clean v1 domain input, secret, output, and permission interface.
5. Pin upstream actions to exact commit SHAs where practical, with version
   comments.
6. Opt into shared IO channels in `devflow.yaml` when the workflow should
   support checkout, artifact download, artifact upload, or writeback.
7. Add checked-in examples under `tests/fixtures/<workflow-id>/`.
8. Add scenario tests under `tests.scenarios` in `devflow.yaml`.
9. Add fixture inputs under `tests/scenarios/<workflow-id>/` when needed.
10. Regenerate synced workflows, docs, and scenario workflows.
11. Run lint, unit tests, local scenarios, docs, and release checks.

## Interface Design

Prefer explicit, consistent input names. Use a stable prefix when passing
through options to another tool or action, such as `checkout-`,
`artifact-download-`, `artifact-upload-`, or `commit-`.

Promoted domain workflows should support the common IO channels unless a channel
is irrelevant to the workflow:

- checkout input through `checkout-*` inputs and `checkout-*` secrets
- artifact input through `artifact-download-*` inputs
- artifact output through `artifact-upload-*` inputs
- opt-in repository writeback through `commit-*` inputs

Declare those channels in `devflow.yaml` instead of copying their inputs and
steps into `workflow.yaml`. The source workflow should describe only the
workflow-specific interface; `devflows sync` expands the public workflow in
`.github/workflows/`.

Keep commit writeback disabled by default, require explicit paths, and isolate
write credentials from the main tool execution when possible. A separate commit
job with `contents: write` is preferable when the main job only needs read
permissions.

Use defaults in `on.workflow_call.inputs.default` when GitHub supports them.
This keeps usage sites simple and makes generated docs more accurate.

Avoid aliases for unpublished draft names. Draft interfaces can change before
the first release.

## Workflow Implementation

Keep reusable workflows narrow and predictable:

- declare top-level permissions
- avoid shell `eval`
- pass untrusted strings through environment variables or structured arguments
- pin third-party actions
- keep test-only behavior out of production workflows
- document any local-runner limitation in tests, not in workflow logic

Keep nontrivial scripts out of workflow YAML. Source support scripts under
`workflows/<workflow-id>/scripts/` and invoke them from a `run:` step through
`${DEVFLOWS_SCRIPT_ROOT}/<workflow-id>/<script>`. At sync time `devflows sync`
_inlines_ each referenced script into the generated workflow: it injects a
"Materialize DevFlows runtime scripts" step (id `devflows-runtime`) that writes
every referenced script verbatim — via a single-quoted heredoc — to
`$RUNNER_TEMP/devflows`, then exports that directory as the step's `script-root`
output, which is what `${DEVFLOWS_SCRIPT_ROOT}` resolves to. Nothing is
published under `.github/workflows/<workflow-id>/`, and the workflow never
checks out the DevFlows repository at run time: the scripts travel inside the
generated YAML, so cross-repo consumers get them without a second checkout (the
earlier `github.workflow_ref` runtime checkout broke those consumers and is
gone).

Declare which jobs receive the materialize step in the `io` block. `io.job` is
the primary runner job that runs the domain scripts; any additional job that
also needs the scripts is listed under `io.runtime-jobs`. Only those jobs may
reference `${DEVFLOWS_SCRIPT_ROOT}` (sync/validate enforces this).

## Generated Outputs

After changing source workflow files, regenerate:

```bash
pixi run -- devflows sync
pixi run -- devflows docs
pixi run -- devflows test-generate
```

`task lint` verifies these generated files are current.
