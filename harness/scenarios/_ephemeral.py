"""Shared ephemeral-branch derivation for the mutation-scenario harness.

``setup-ephemeral-writeback.py`` (which creates and pushes the branch) and
``cleanup-ephemeral-branch.py`` (which deletes it) must agree on how an ephemeral
branch name is derived from the branch prefix and the run identifiers. Keeping
that derivation in one module guarantees they never drift apart, and lets both
scripts stay thin and unit-testable.
"""

from __future__ import annotations


def branch_name(prefix: str, run_id: str, run_attempt: str) -> str:
    """Ephemeral branch pushed by one attempt of a mutation-scenario run."""
    return f"{prefix}-{run_id}-{run_attempt}"


def artifact_name(base: str, run_id: str, run_attempt: str) -> str:
    """Run-scoped writeback payload artifact name for one attempt."""
    return f"{base}-{run_id}-{run_attempt}"


def run_branch_glob(prefix: str, run_id: str) -> str:
    """Glob matching every attempt's branch for a single run.

    "Re-run failed jobs" bumps ``GITHUB_RUN_ATTEMPT`` while the setup job's frozen
    outputs still name an earlier attempt's branch, so one run can leave several
    ``{prefix}-{run_id}-{attempt}`` branches behind. Cleanup deletes the whole
    family rather than a single recomputed name, so no attempt is orphaned.
    """
    return f"{prefix}-{run_id}-*"


def parse_ls_remote_heads(stdout: str) -> list[str]:
    """Branch short-names from ``git ls-remote --heads`` output."""
    heads_prefix = "refs/heads/"
    branches: list[str] = []
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        ref = line.split("\t", 1)[1].strip()
        if ref.startswith(heads_prefix):
            branches.append(ref[len(heads_prefix) :])
    return branches


def is_already_deleted(stderr: str) -> bool:
    """Whether ``git push --delete`` failed only because the ref was already gone.

    A concurrent cleanup (or a re-run) can race the delete; a missing ref is the
    expected, benign outcome. Any other stderr is a real error the caller must
    surface instead of swallowing.
    """
    lowered = stderr.lower()
    return "remote ref does not exist" in lowered or "unable to delete" in lowered
