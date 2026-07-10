from __future__ import annotations

import os
import subprocess

# Recompute the ephemeral branch name deterministically instead of reading it from
# the setup job's outputs. If setup fails after pushing the branch but before
# emitting outputs, an output-keyed cleanup would skip and orphan the branch. The
# name is a pure function of the branch prefix and the run identifiers, so cleanup
# can always reconstruct it and delete the branch.
branch = (
    f"{os.environ['DEVFLOWS_BRANCH_PREFIX']}-"
    f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
)

result = subprocess.run(["git", "push", "origin", "--delete", branch], check=False)
if result.returncode != 0:
    print(f"Branch {branch} was already absent or never pushed; skipping delete.")
