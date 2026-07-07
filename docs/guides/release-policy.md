# Release Policy

DevFlows uses independent SemVer for each promoted workflow. Tags are scoped by
workflow ID:

- Exact release: `workflow-id/v1.2.3`
- Moving minor: `workflow-id/v1.2`
- Moving major: `workflow-id/v1`

Release Please manages per-workflow changelogs and release pull requests.
Consumers that need maximum reproducibility should pin to an exact tag or commit
SHA.

Run `task release:dry-run` to validate the local release configuration before
opening a pull request. The hosted release workflow uses release-please after
the configuration has landed on the default branch.
