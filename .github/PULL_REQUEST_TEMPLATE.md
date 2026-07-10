<!--
Thanks for contributing to DevFlows! Please complete the checklist below.
See CONTRIBUTING.md for details.
-->

## Summary

<!-- What does this PR change, and why? -->

## Related issues

<!-- e.g. Closes #123 -->

## Checklist

- [ ] PR title follows
      [Conventional Commits](https://www.conventionalcommits.org/) (e.g.
      `feat(pandoc): ...`, `fix(writeback): ...`).
- [ ] I edited workflow **sources** under `workflows/<id>/`, not the generated
      files in `.github/workflows/`.
- [ ] Regenerated outputs are committed (`devflows sync`, `devflows docs`,
      `devflows test-generate`) and `pixi run lint` passes.
- [ ] Tests were added or updated for the change (`pixi run test`, and scenario
      tests where relevant).
- [ ] Documentation was added or updated (user guide and/or dev guide).
