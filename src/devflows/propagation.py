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
differs *semantically* from the base ref, it requires the same change set to also
touch that workflow's package path so release-please can attribute a release to
it. A formatting-only re-render (e.g. a YAML dumper width change) alters the
bytes but not the parsed meaning, so it strands no consumer and is not a
violation — ``published_content_changed`` distinguishes the two by comparing
parsed documents. The pure ``propagation_violations`` function is unit-tested;
the CLI wrapper feeds it the list of files ``git`` reports as changed plus a
semantic-change predicate.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from devflows.yaml import load_yaml_text


def published_workflow_path(workflow_id: str) -> str:
    """Path of the generated reusable workflow for ``workflow_id``."""
    return f".github/workflows/{workflow_id}.yaml"


def package_prefix(workflow_id: str) -> str:
    """release-please package path prefix for ``workflow_id``."""
    return f"workflows/{workflow_id}/"


def _git_show(ref: str, path: str) -> str | None:
    """Return the text of ``path`` at ``ref``, or None if it does not exist there."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def published_content_changed(base_ref: str, workflow_id: str) -> bool:
    """True when the published workflow's *parsed* content differs from ``base_ref``.

    The propagation guard exists to stop a shared-generator change from stranding
    consumers on stale CODE — i.e. a *behavioral* difference. A pure re-rendering
    (a YAML dumper width change, key-order normalization, or any reformatting)
    changes the file's bytes but not its meaning: it parses to the identical data,
    so no consumer is stranded and it is not a propagation violation. Comparing the
    parsed documents (rather than raw text) is what distinguishes the two. A file
    absent on either side (added/removed) is conservatively treated as changed.
    """
    base = _git_show(base_ref, published_workflow_path(workflow_id))
    head_path = Path(published_workflow_path(workflow_id))
    head = head_path.read_text(encoding="utf-8") if head_path.is_file() else None
    if base is None or head is None:
        return True
    try:
        return load_yaml_text(base) != load_yaml_text(head)
    except Exception:
        # If either revision fails to parse, be conservative and flag it.
        return True


def propagation_violations(
    changed_paths: list[str],
    workflow_ids: list[str],
    *,
    published_semantically_changed: Callable[[str], bool] | None = None,
) -> list[str]:
    """Return an error per workflow whose published output changed unpropagated.

    A violation is a workflow whose generated ``.github/workflows/<id>.yaml``
    appears in ``changed_paths`` while no path under ``workflows/<id>/`` does, so
    release-please would attribute no release to it.

    When ``published_semantically_changed`` is supplied, a candidate is dropped if
    the callback reports the published output did not change *semantically* (a
    formatting-only re-render), because that strands no consumer. Omitting the
    callback keeps the pure path-based behavior (used by unit tests).
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
        if published_semantically_changed is not None and not published_semantically_changed(
            workflow_id
        ):
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
