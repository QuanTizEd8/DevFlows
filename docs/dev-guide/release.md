# Release Management

DevFlows releases workflows independently. A change to one workflow should not
force a release of every workflow in the repository.

## Versioning Policy

Each workflow uses SemVer with workflow-scoped tags:

- exact release: `workflow-id/vX.Y.Z` (always published)
- moving major: `workflow-id/vN` (published from `1.0.0` onward)

Moving **minor** tags are intentionally not published. Consumers pin an exact
release or a commit SHA, and from `1.0.0` may pin a moving major tag for
compatible updates.

### 0.x pre-completion contract

The catalog ships pre-1.0. Every workflow's release-please manifest version is
on a `0.x` line and its `devflow.yaml` `release.major` is `0`. While a workflow
is pre-1.0:

- Breaking changes are released as **minor** bumps, not major bumps. This is
  enforced by `bump-minor-pre-major: true` in
  `.github/release-please/config.json`, so a breaking change never accidentally
  promotes a workflow to `1.0.0`.
- Moving major tags are **not** published (the tag automation below is dormant
  by construction while the major is `0`).
- The 0.x line carries no cross-release compatibility promise.

### `release.major` semantics

`devflow.yaml`'s `release.major` records the **current released major version
line** for the workflow (an integer, `0` while pre-1.0). `task release-check`
cross-validates that it equals the major component of the workflow's
release-please manifest version, so the two can never silently diverge.

### Promoting a workflow from 0.x to 1.0

Promotion is deliberate and per-workflow: it starts a workflow's compatibility
promise and activates its moving `<id>/vMAJOR` tag.

**Do not promote by hand-editing `.github/release-please/manifest.json` to
`1.0.0`.** In manifest mode the manifest records the **last released** version,
so writing `1.0.0` there tells release-please that `1.0.0` is _already out_. It
then computes the _next_ version from `1.0.0`, cuts **no** `<id>/v1.0.0` tag,
and — because no release is produced — `.dev/scripts/move_major_tags.py` never
runs, so `<id>/v1` is never created. That is the trap the previous procedure
fell into.

Instead, force the version with release-please's documented one-time
`Release-As` commit footer (see the
[release-please README](https://github.com/googleapis/release-please)) and move
`release.major` in lockstep _inside the release pull request_.

**Prerequisite:** provision `RELEASE_PLEASE_TOKEN` first (see the "Release Token
(PAT) Setup" section below). Without it release-please still opens the release
PR under `github.token`, but that PR does not trigger CI, so you cannot watch
`release-check` go green before merging.

To promote one workflow `<id>`:

1. **Trigger the forced version.** Land a small commit on `main` that touches
   the workflow's package path (`workflows/<id>/` — for example a one-line
   `devflow.yaml` note recording the promotion) and carries a `Release-As`
   footer. The path touch matters: in manifest mode release-please attributes
   the forced version to the component whose files the commit changed.

   ```bash
   git commit -m "chore(<id>): promote to 1.0.0" -m "Release-As: 1.0.0"
   ```

   Do **not** touch `manifest.json` or `release.major` in this commit. On `main`
   the manifest is still `0.x` and `release.major` is still `0`, so
   `task release-check` stays green.

2. **Let release-please open the release PR.** `DevFlows Release` runs
   release-please, which opens a release pull request that bumps
   `.github/release-please/manifest.json` for `workflows/<id>` to `1.0.0` and
   writes the changelog. On that PR branch the manifest is `1.0.0` but
   `release.major` is still `0`, so its `release-check` is **red** — this is
   expected and you fix it in the next step. It is not a deadlock (see below).

3. **Move `release.major` in lockstep, in the same PR.** On the release PR
   branch, bump `release.major` from `0` to `1` in
   `workflows/<id>/devflow.yaml`, then regenerate and commit any generated
   changes (`task sync`, `task docs`, `task test-generate`) — `release.major`
   feeds the generated reference page's recommended pin. Now the PR carries the
   manifest bump (from release-please) **and** the `release.major` bump (from
   you), so `task release-check` passes: the manifest major and `release.major`
   are both `1`.

4. **Merge the release PR.** Both flips land on `main` in the same merge, so
   `main` is never committed in an inconsistent state. release-please creates
   the `<id>/v1.0.0` tag and GitHub release; because the released major is now
   `>= 1`, the `Force-move moving major tags` step runs
   `.dev/scripts/move_major_tags.py` and creates/moves `<id>/v1`.

**Why there is no deadlock.** `task release-check` only ever compares the
**committed** state of `main`, where `release.major` must equal the manifest
major. The manifest bump (from release-please) and the `release.major` bump
(from you) travel together in the one release PR, so they become consistent
atomically on merge — `main` never holds a mismatched pair. The transient red on
the freshly-opened release PR is cleared by step 3 before merge; no ordering
forces a permanent failure. (The audit's "deadlock" concern assumed
`release.major` had to be bumped in a _separate, earlier_ commit on `main`; it
does not — it rides the release PR.)

Repeat these steps for each of the 14 workflows as it is ready. Each gets its
own `Release-As` commit and its own release PR, and you bump that workflow's
`release.major` in its PR — a change to one workflow never forces another to
promote. (release-please's sticky
[`release-as` config key](https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md)
is an alternative to the commit footer, but it pins _every_ future release to
that version until you remove it; prefer the one-time footer.)

## Release Please

Release Please is configured in manifest mode:

- `.github/release-please/config.json`
- `.github/release-please/manifest.json`

Each active workflow must have a matching package entry. `task release-check`
validates that release-please configuration matches the active catalog.

## Changelogs

Per-workflow changelogs are managed by Release Please. Changelog paths are
configured per package in `.github/release-please/config.json`.

## Commit Messages

Use Conventional Commits. Prefer workflow scopes for workflow behavior changes:

```text
feat(pandoc): add working-directory scenario coverage
fix(pandoc): preserve checkout defaults
docs(pandoc): document extra image template path
test(pandoc): add hosted artifact assertions
```

Changes to shared tooling can use scopes such as `cli`, `docs`, `test`, or
`release`.

## Release Checks

Before opening a release-related pull request:

```bash
task release-check
```

The hosted release workflow runs Release Please after the configuration lands on
the default branch.

## Shared-Generator Propagation

The published reusable workflows in `.github/workflows/<id>.yaml` are generated
from `workflows/<id>/` **plus** the shared generator in `.dev/src/devflows/`
(notably the IO-channel templates in `publish.py` and the SHA-pin registry in
`actions.py`). release-please attributes a release to a workflow only from
commits that touch that workflow's package path (`workflows/<id>/`); the commit
_scope_ is cosmetic. So a change to the shared generator can alter a workflow's
published output while release-please cuts no release for it, stranding
consumers on stale code.

`task propagation-check` (run on every pull request, and available locally
against a base ref via `DEVFLOWS_BASE_SHA`) fails when a workflow's
`.github/workflows/<id>.yaml` changed but nothing under `workflows/<id>/` did.

**Runbook when you change the shared generator:**

1. Make the generator change and run `task sync` to regenerate published
   workflows.
2. Inspect which `.github/workflows/<id>.yaml` files changed.
3. For every affected workflow, land a source change under `workflows/<id>/` (a
   real edit — for example note the interface/behavior change in its
   `devflow.yaml` `notes`) in the same pull request, with a conventional commit
   such as `fix(<id>): regenerate for shared checkout input`. This is what makes
   release-please cut a release for that workflow.
4. If a regenerated diff is genuinely consumer-neutral, revert that workflow's
   output rather than shipping an unreleased change.

`task propagation-check` enforces steps 2–3 in CI.

## Moving Major Tag Automation

Release automation publishes immutable exact tags (`<id>/vX.Y.Z`) for every
release. Once a workflow is released at major `>= 1`, the
`Force-move moving major tags` step in `_release.yaml` additionally
force-updates `<id>/v<major>` onto that release's commit. The logic lives in
`.dev/scripts/move_major_tags.py` (`compute_major_tag_moves`, unit-tested in
`tests/internal/test_release_tags.py`) and reads the release-please-action
outputs.

The automation is **dormant during `0.x`** by construction: every released major
is `0`, so `compute_major_tag_moves` returns nothing and no tag is moved. It is
already wired in, so the first `1.0.0` release needs no new machinery. Moving
minor tags are never published.

## Release Token (PAT) Setup

`_release.yaml` uses `secrets.RELEASE_PLEASE_TOKEN` for both the release-please
step and the moving-major-tag push, falling back to `github.token` so the
workflow runs before the secret exists. A fine-grained PAT is required so that
release pull requests trigger CI (pull requests opened with the default
`GITHUB_TOKEN` do not start workflow runs) and so tag pushes are attributed to a
real identity.

Owner setup:

- **Token type:** fine-grained personal access token (a GitHub App token works
  too; PAT is simpler for a single repo).
- **Resource owner / repository:** `QuanTizEd8`, scoped to **only**
  `QuanTizEd8/DevFlows`.
- **Repository permissions:** `Contents: Read and write` (create tags, releases,
  and the release branch) and `Pull requests: Read and write` (open/update
  release PRs). No account or organization permissions are needed.
- **Expiry:** the shortest that is operationally comfortable — 90 days is a good
  default; calendar a rotation reminder.
- **Secret name:** add it as the repository Actions secret
  `RELEASE_PLEASE_TOKEN` (Settings → Secrets and variables → Actions). The
  workflow keeps working with the `github.token` fallback until this is set,
  minus the CI-on-release-PR benefit.

## Owner setup: repository rulesets

Two rulesets protect the release artifacts. Configure them once, under
**Settings → Rules → Rulesets**.

### Tag ruleset (`*/v*`)

Protect the workflow-scoped release tags so a release is immutable once cut:

- **Target:** tags matching `*/v*` (covers exact tags `<id>/vX.Y.Z` and moving
  major tags `<id>/vN`).
- **Rules:** restrict **updates** and restrict **deletions**. This makes exact
  release tags immutable and blocks accidental tag deletion.
- **Bypass:** the release identity **must** be on the bypass list. The
  `Force-move moving major tags` step force-pushes `<id>/v<major>` via
  `.dev/scripts/move_major_tags.py`, which is an update to a protected tag;
  without a bypass for the `RELEASE_PLEASE_TOKEN` identity that push is
  rejected. (During `0.x` the automation is dormant, but configure the bypass
  before the first `1.0.0` so the promotion does not fail.)

### Branch protection for `main`

Protect `main` with a branch ruleset that requires pull requests and the CI
status checks below to pass before merge. Name each required check exactly as
the job reports it:

- **`Validate`** — the lint/test/propagation job in `_ci.yaml`.
- **`Adapter contract`** — the pin/contract job in `_ci.yaml` (it runs only when
  an action pin or a consuming workflow changes; on other PRs it completes
  without running the network test, so it stays a safe required check).
- **`Analyze Python`** — the CodeQL job in `_codeql.yaml`.
- **`Build`** — the docs build job in `_docs.yaml` (it builds on PRs and only
  deploys Pages on `main`).
- Scenario assertion jobs (the `*_assert` jobs) can be added as required checks
  **once they are stable**; until then keep them informational so a
  hosted-runner flake does not block unrelated merges. These jobs now live
  across the per-workflow `_scenarios-<id>.yaml` files rather than a single
  `devflows-scenarios.yaml`, but a required status check is keyed on the job's
  reported **name** (its check context), not the file it lives in, and those
  names are unchanged by the split — each still reads as
  `<Workflow name>: <scenario> assertions` (e.g. `Pandoc: … assertions`) and
  stays unique because it embeds the workflow name. So add the specific
  assertion jobs you want to gate on by name, exactly as before. GitHub cannot
  require "all scenario workflows" as one check (there is no single aggregate
  context across files); if you want one gate to wait on the whole suite, add a
  tiny `workflow_run`-triggered job that `needs` nothing but reports success
  once the scenario workflows for the ref complete, and require that. That
  aggregation is optional and unnecessary while the assertion jobs are
  informational.

Also enable "restrict deletions" and "block force pushes" on `main`.

## Release Runbook

1. Merge feature/fix pull requests to `main` using Conventional Commits and, for
   shared-generator changes, satisfy the propagation guard (above).
2. `DevFlows Release` runs release-please on `main` and opens/updates a release
   pull request per workflow.
3. Review the release pull request (version bump, changelog). With the PAT
   configured, CI runs on it; require it green before merging.
4. Merge the release pull request. release-please creates the `<id>/vX.Y.Z` tag
   and GitHub release; the tag-automation step moves `<id>/v<major>` when the
   major is `>= 1`.
