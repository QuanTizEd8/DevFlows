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
4. Define a clean v1 input, secret, output, and permission interface.
5. Pin upstream actions to exact commit SHAs where practical, with version
   comments.
6. Add checked-in examples under `test/fixtures/<workflow-id>/`.
7. Add scenario tests under `tests.scenarios` in `devflow.yaml`.
8. Add fixture inputs under `test/scenarios/<workflow-id>/` when needed.
9. Regenerate synced workflows, docs, and scenario workflows.
10. Run lint, unit tests, local scenarios, docs, and release checks.

## Interface Design

Prefer explicit, consistent input names. Use a stable prefix when passing
through options to another tool or action, such as `checkout-`,
`artifact-download-`, `artifact-upload-`, or `commit-`.

Promoted workflows should support the common IO channels unless a channel is
irrelevant to the workflow:

- checkout input through `checkout-*` inputs and `checkout-*` secrets
- artifact input through `artifact-download-*` inputs
- artifact output through `artifact-upload-*` inputs
- opt-in repository writeback through `commit-*` inputs

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
`workflows/<workflow-id>/scripts/`; `devflows sync` publishes them under
`.github/workflows/<workflow-id>/...` next to the reusable workflow. Public
reusable workflows that need those files should check out the DevFlows runtime
repository at `github.workflow_ref` and execute the synced script from that
checkout.

## Generated Outputs

After changing source workflow files, regenerate:

```bash
pixi run devflows sync
pixi run devflows docs
pixi run devflows test-generate
```

`pixi run lint` verifies these generated files are current.
