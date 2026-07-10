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

# Runtime scripts for the published workflows are no longer copied under
# .github/workflows/<id>/ (they are inlined at sync time). This harness, however,
# runs inside the DevFlows repo with a full checkout available, so it invokes the
# writeback create-payload script directly from its catalog source.
CREATE_PAYLOAD_SCRIPT = "workflows/writeback/scripts/create-payload.py"


def _write_output(key: str, value: str) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"{key}={value}\n")


workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
fixture_path = Path(os.environ["DEVFLOWS_FIXTURE_PATH"])
payload_dir = workspace / ".devflows-writeback" / "payload"
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

shutil.rmtree(workspace / fixture_path, ignore_errors=True)
for item in payload_files:
    path = workspace / fixture_path / item["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(item.get("content", "")), encoding="utf-8")

create_payload_env = {
    **os.environ,
    "WRITEBACK_PAYLOAD_DIR": str(payload_dir),
    "WRITEBACK_PATHS": "\n".join((fixture_path / path).as_posix() for path in payload_paths),
    "WRITEBACK_DELETE_PATHS": "\n".join((fixture_path / path).as_posix() for path in delete_paths),
    "WRITEBACK_SOURCE_REPOSITORY": os.environ["GITHUB_REPOSITORY"],
    "WRITEBACK_SOURCE_REF": branch,
    "WRITEBACK_SOURCE_SHA": base_sha,
}
subprocess.run(
    ["python", CREATE_PAYLOAD_SCRIPT],
    check=True,
    env=create_payload_env,
)
