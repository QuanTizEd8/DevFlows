from __future__ import annotations

import os
import subprocess

branch = os.environ.get("DEVFLOWS_BRANCH", "").strip()
if not branch:
    print("No ephemeral branch output was available; skipping cleanup.")
else:
    subprocess.run(["git", "push", "origin", "--delete", branch], check=True)
