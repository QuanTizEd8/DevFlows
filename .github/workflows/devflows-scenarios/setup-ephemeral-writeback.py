from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
fixture_path = Path(os.environ["DEVFLOWS_FIXTURE_PATH"])
payload_dir = workspace / ".devflows-writeback" / "payload"
artifact_name = (
    f"{os.environ['DEVFLOWS_ARTIFACT_NAME']}-"
    f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
)
branch = (
    f"{os.environ['DEVFLOWS_BRANCH_PREFIX']}-"
    f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
)
initial_files = json.loads(os.environ["DEVFLOWS_INITIAL_FILES"])
payload_files = json.loads(os.environ["DEVFLOWS_PAYLOAD_FILES"])
payload_paths = json.loads(os.environ["DEVFLOWS_PAYLOAD_PATHS"])
delete_paths = json.loads(os.environ["DEVFLOWS_DELETE_PATHS"])

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
    ["python", ".github/workflows/writeback/create-payload.py"],
    check=True,
    env=create_payload_env,
)

with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"branch={branch}\n")
    output.write(f"base-sha={base_sha}\n")
    output.write(f"artifact-name={artifact_name}\n")
