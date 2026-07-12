"""Apply an emitted workspace patch to a checked-out branch, then commit and push.

The writeback workflow checks the target branch out, downloads a patch artifact
(changes.patch, produced by any workflow's patch-emit channel), and runs this
script. The patch is git-applied to the checkout with --index --3way so it still
applies when the target branch advanced past the SHA the patch was generated
against (git falls back to a three-way merge using the base blobs named in the
patch, as long as they are reachable in the target's object database). git apply
is the trust boundary here (it refuses paths that escape the repo and will not
follow a symlink out of the tree); the job's contents: write permission -- held
only by this workflow -- is what makes the write authoritative.

All git commands run in the current working directory, which the workflow's run
step sets to the checked-out target (GITHUB_WORKSPACE). No caller input is
interpolated into a shell; every value arrives through an environment variable.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    patch_file = Path(os.environ["WRITEBACK_PATCH_FILE"]).resolve()
    expected_base_sha = os.environ.get("WRITEBACK_EXPECTED_BASE_SHA", "").strip()

    if not patch_file.is_file():
        raise SystemExit(f"Writeback patch file was not found: {patch_file}")

    if expected_base_sha:
        actual_sha = _git_stdout("rev-parse", "HEAD")
        if actual_sha != expected_base_sha:
            raise SystemExit(f"Target checkout is at {actual_sha}, expected {expected_base_sha}.")

    # An empty patch (the patch-emit channel writes one when the source workspace
    # had no changes) is a clean no-op, not an error.
    if not patch_file.read_bytes().strip():
        print("Writeback patch is empty; nothing to apply.")
        return 0

    _git("config", "user.name", os.environ["COMMIT_AUTHOR_NAME"])
    _git("config", "user.email", os.environ["COMMIT_AUTHOR_EMAIL"])

    result = subprocess.run(
        ["git", "apply", "--index", "--3way", "--verbose", str(patch_file)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(
            "git apply could not apply the workspace patch"
            + (f":\n{detail}" if detail else ".")
            + "\nThe patch conflicts with the target branch; regenerate it against the "
            "current branch tip (or pass commit-expected-base-sha to fail fast on drift)."
        )

    if _git_quiet("diff", "--cached", "--quiet"):
        print("No changes to commit.")
        return 0

    _git("commit", "-m", os.environ["COMMIT_MESSAGE"])
    if os.environ["COMMIT_PUSH"].lower() == "true":
        _git("push", "origin", f"HEAD:{os.environ['COMMIT_BRANCH']}")
    return 0


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


def _git_quiet(*args: str) -> bool:
    return subprocess.run(["git", *args], check=False).returncode == 0


def _git_stdout(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    sys.exit(main())
