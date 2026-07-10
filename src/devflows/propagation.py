"""Shared-generator release-propagation guard.

release-please attributes a commit to a workflow package by the files the commit
changes under that package's path (``workflows/<id>/``); the commit *scope* is
cosmetic. But a change to the shared generator (``src/devflows/``, notably the
IO-channel templates in ``publish.py`` and the SHA-pin registry in
``actions.py``) regenerates the published artifact ``.github/workflows/<id>.yaml``
for potentially every workflow while touching nothing under ``workflows/<id>/``.
Such a change would silently strand consumers: their published workflow changed,
yet release-please cuts no release for it.

This guard makes that failure loud. For every workflow whose published output
differs from the base ref, it requires the same change set to also touch that
workflow's package path so release-please can attribute a release to it. The
pure ``propagation_violations`` function is unit-tested; the CLI wrapper feeds it
the list of files ``git`` reports as changed.
"""

from __future__ import annotations

import subprocess


def published_workflow_path(workflow_id: str) -> str:
    """Path of the generated reusable workflow for ``workflow_id``."""
    return f".github/workflows/{workflow_id}.yaml"


def package_prefix(workflow_id: str) -> str:
    """release-please package path prefix for ``workflow_id``."""
    return f"workflows/{workflow_id}/"


def propagation_violations(changed_paths: list[str], workflow_ids: list[str]) -> list[str]:
    """Return an error per workflow whose published output changed unpropagated.

    A violation is a workflow whose generated ``.github/workflows/<id>.yaml``
    appears in ``changed_paths`` while no path under ``workflows/<id>/`` does, so
    release-please would attribute no release to it.
    """
    changed = set(changed_paths)
    violations: list[str] = []
    for workflow_id in workflow_ids:
        published = published_workflow_path(workflow_id)
        if published not in changed:
            continue
        prefix = package_prefix(workflow_id)
        if any(path.startswith(prefix) for path in changed):
            continue
        violations.append(
            f"{published} changed but nothing under {prefix} did. A shared-generator "
            f"change altered {workflow_id!r}'s published workflow without a change "
            f"release-please can attribute to it, so consumers pinned to a {workflow_id} "
            f"tag would be stranded on stale code. Land a source change under {prefix} "
            f"(a conventional commit such as 'fix({workflow_id}): regenerate for <shared "
            f"change>') so release-please cuts a {workflow_id} release, or revert the "
            f"generator change for this workflow."
        )
    return violations


def changed_paths_since(base_ref: str) -> list[str]:
    """Files changed between ``base_ref`` and HEAD (three-dot: since merge-base)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
