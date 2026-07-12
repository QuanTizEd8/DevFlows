from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Make the sibling helper importable whether this runs as `python <path>` (which
# puts the dir on sys.path) or via runpy in the unit tests (which does not).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ephemeral import artifact_name, branch_name  # noqa: E402


def _write_output(key: str, value: str) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"{key}={value}\n")


workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
fixture_path = Path(os.environ["DEVFLOWS_FIXTURE_PATH"])
patch_dir = workspace / ".devflows-patch"
run_id = os.environ["GITHUB_RUN_ID"]
run_attempt = os.environ["GITHUB_RUN_ATTEMPT"]
# Derive the branch/artifact names from the shared helper so cleanup, which globs
# {prefix}-{run_id}-*, always matches whatever this setup pushed.
artifact = artifact_name(os.environ["DEVFLOWS_ARTIFACT_NAME"], run_id, run_attempt)
branch = branch_name(os.environ["DEVFLOWS_BRANCH_PREFIX"], run_id, run_attempt)
initial_files = json.loads(os.environ["DEVFLOWS_INITIAL_FILES"])
payload_files = json.loads(os.environ["DEVFLOWS_PAYLOAD_FILES"])
payload_paths = json.loads(os.environ["DEVFLOWS_PAYLOAD_PATHS"])
delete_paths = json.loads(os.environ["DEVFLOWS_DELETE_PATHS"])

# Flush the deterministic names before any git operation. If this step fails
# after the branch is pushed but before completing, downstream jobs still see the
# branch/artifact names. Cleanup does not depend on these outputs (it recomputes
# the deterministic branch name), so an orphaned branch is deleted regardless.
_write_output("branch", branch)
_write_output("artifact-name", artifact)

subprocess.run(["git", "config", "user.name", "DevFlows E2E"], check=True)
subprocess.run(["git", "config", "user.email", "devflows-e2e@example.test"], check=True)
subprocess.run(["git", "switch", "-c", branch], check=True)

for item in initial_files:
    path = workspace / fixture_path / item["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(item.get("content", "")), encoding="utf-8")

subprocess.run(["git", "add", "--", fixture_path.as_posix()], check=True)
subprocess.run(["git", "commit", "-m", "test: prepare writeback e2e branch"], check=True)
subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], check=True)
base_sha = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
_write_output("base-sha", base_sha)

# Transform the workspace to the desired end state, then capture it as a single
# patch (mirroring the patch-emit channel: git add -A; git diff --cached --binary;
# git reset). Replace paths are directory replacements, so their subtree is cleared
# before the payload files are written; delete paths are removed best-effort (an
# already-absent delete is a no-op, exercised by the writeback scenario).
for replace_path in payload_paths:
    shutil.rmtree(workspace / fixture_path / replace_path, ignore_errors=True)
for delete_path in delete_paths:
    target = workspace / fixture_path / delete_path
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    elif target.exists() or target.is_symlink():
        target.unlink()
for item in payload_files:
    path = workspace / fixture_path / item["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(item.get("content", "")), encoding="utf-8")

subprocess.run(["git", "add", "-A"], check=True)
patch = subprocess.run(
    ["git", "diff", "--cached", "--binary"],
    check=True,
    capture_output=True,
).stdout
subprocess.run(["git", "reset", "-q"], check=True)

patch_dir.mkdir(parents=True, exist_ok=True)
(patch_dir / "changes.patch").write_bytes(patch)
