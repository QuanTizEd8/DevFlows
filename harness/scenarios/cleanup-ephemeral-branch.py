from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Make the sibling helper importable whether this runs as `python <path>` (which
# puts the dir on sys.path) or via runpy in the unit tests (which does not).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ephemeral import (  # noqa: E402
    is_already_deleted,
    parse_ls_remote_heads,
    run_branch_glob,
)


def main() -> None:
    glob = run_branch_glob(os.environ["DEVFLOWS_BRANCH_PREFIX"], os.environ["GITHUB_RUN_ID"])
    # Delete every ephemeral branch this run pushed across attempts. A "Re-run
    # failed jobs" bumps GITHUB_RUN_ATTEMPT, so recomputing a single name from the
    # current attempt would miss an earlier attempt's branch and orphan it.
    listing = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", glob],
        check=True,
        capture_output=True,
        text=True,
    )
    branches = parse_ls_remote_heads(listing.stdout)
    if not branches:
        print(f"No ephemeral branches matching {glob} to delete.")
        return
    for branch in branches:
        deletion = subprocess.run(
            ["git", "push", "origin", "--delete", branch],
            capture_output=True,
            text=True,
        )
        if deletion.returncode == 0:
            print(f"Deleted ephemeral branch {branch}.")
            continue
        # A missing ref (already deleted, e.g. by a racing cleanup) is fine; any
        # other git failure is unexpected and must fail the job rather than be
        # silently swallowed.
        if is_already_deleted(deletion.stderr):
            print(f"Branch {branch} was already absent; continuing.")
            continue
        raise SystemExit(f"failed to delete ephemeral branch {branch}: {deletion.stderr.strip()}")


if __name__ == "__main__":
    main()
