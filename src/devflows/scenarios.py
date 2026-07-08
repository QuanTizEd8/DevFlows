from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devflows.catalog import Workflow
from devflows.yaml import dump_yaml

GENERATED_HOSTED_PATH = Path(".github/workflows/devflows-scenarios.yaml")
GENERATED_LOCAL_PATH = Path(".github/workflows/devflows-local-scenarios.yaml")
GENERATED_SCRIPT_DIR = Path(".github/workflows/devflows-scenarios")
LOCAL_EVENT_PATH = Path(".act/push.json")
DOWNLOAD_ARTIFACT_REF = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
UPLOAD_ARTIFACT_REF = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
CHECKOUT_REF = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
ACT_PLATFORM = "ubuntu-latest=catthehacker/ubuntu:act-latest"
SCENARIO_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SCENARIO_SCRIPTS = {
    "assert-result.py": """\
from __future__ import annotations

import os

actual = os.environ["ACTUAL_RESULT"]
if actual != "success":
    raise SystemExit(f"Expected scenario job to succeed, got {actual!r}.")
""",
    "assert-equals.py": """\
from __future__ import annotations

import os

name = os.environ["ASSERT_NAME"]
expected = os.environ["EXPECTED"]
actual = os.environ["ACTUAL"]
if actual != expected:
    raise SystemExit(f"{name}: expected {expected!r}, got {actual!r}.")
""",
    "assert-file-exists.py": """\
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["ASSERT_PATH"])
if not path.is_file():
    raise SystemExit(f"Expected file to exist: {path}")
""",
    "assert-file-contains.py": """\
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["ASSERT_PATH"])
text = os.environ["ASSERT_TEXT"]
if not path.is_file():
    raise SystemExit(f"Expected file to exist: {path}")
content = path.read_text(encoding="utf-8")
if text not in content:
    raise SystemExit(f"Expected {path} to contain {text!r}.")
""",
    "create-setup-files.py": """\
from __future__ import annotations

import json
import os
from pathlib import Path

files = json.loads(os.environ["DEVFLOWS_SETUP_FILES"])
for item in files:
    path = Path(item["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(item.get("content", "")), encoding="utf-8")
""",
    "setup-ephemeral-writeback.py": """\
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
    "WRITEBACK_PATHS": "\\n".join((fixture_path / path).as_posix() for path in payload_paths),
    "WRITEBACK_DELETE_PATHS": "\\n".join((fixture_path / path).as_posix() for path in delete_paths),
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
    output.write(f"branch={branch}\\n")
    output.write(f"base-sha={base_sha}\\n")
    output.write(f"artifact-name={artifact_name}\\n")
""",
    "assert-ephemeral-writeback.py": """\
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

fixture_path = Path(os.environ["DEVFLOWS_FIXTURE_PATH"])
assertions = json.loads(os.environ["DEVFLOWS_ASSERTIONS"])

for assertion in assertions:
    assertion_type = assertion["type"]
    if assertion_type == "branch-file-contains":
        path = fixture_path / assertion["path"]
        if not path.is_file():
            raise SystemExit(f"Expected file to exist: {path}")
        text = str(assertion["text"])
        content = path.read_text(encoding="utf-8")
        if text not in content:
            raise SystemExit(f"Expected {path} to contain {text!r}.")
    elif assertion_type == "branch-file-missing":
        path = fixture_path / assertion["path"]
        if path.exists():
            raise SystemExit(f"Expected path to be absent: {path}")
    elif assertion_type == "latest-commit-message-equals":
        actual = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        expected = str(assertion["value"])
        if actual != expected:
            raise SystemExit(f"Expected latest commit message {expected!r}, got {actual!r}.")
    else:
        raise SystemExit(f"Unsupported branch assertion type: {assertion_type}")
""",
    "cleanup-ephemeral-branch.py": """\
from __future__ import annotations

import os
import subprocess

branch = os.environ.get("DEVFLOWS_BRANCH", "").strip()
if not branch:
    print("No ephemeral branch output was available; skipping cleanup.")
else:
    subprocess.run(["git", "push", "origin", "--delete", branch], check=True)
""",
}


@dataclass(frozen=True)
class Scenario:
    workflow: Workflow
    id: str
    name: str
    runs: tuple[str, ...]
    inputs: dict[str, Any]
    assertions: tuple[dict[str, Any], ...]
    cleanup: tuple[str, ...]
    artifact: dict[str, Any]
    setup_artifact: dict[str, Any]
    mutation: dict[str, Any]
    writeback_payload: dict[str, Any]

    @property
    def job_prefix(self) -> str:
        return f"{self.workflow.id}-{self.id}".replace("-", "_")


def load_scenarios(workflows: list[Workflow]) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for workflow in workflows:
        for raw_scenario in workflow.metadata.get("tests", {}).get("scenarios", []) or []:
            if not isinstance(raw_scenario, dict):
                continue
            scenarios.append(
                Scenario(
                    workflow=workflow,
                    id=str(raw_scenario.get("id") or ""),
                    name=str(raw_scenario.get("name") or raw_scenario.get("id") or ""),
                    runs=tuple(str(item) for item in raw_scenario.get("runs", []) or []),
                    inputs=dict(raw_scenario.get("inputs") or {}),
                    assertions=tuple(
                        dict(assertion) for assertion in raw_scenario.get("assertions", []) or []
                    ),
                    cleanup=tuple(str(path) for path in raw_scenario.get("cleanup", []) or []),
                    artifact=dict(raw_scenario.get("artifact") or {}),
                    setup_artifact=dict(raw_scenario.get("setup-artifact") or {}),
                    mutation=dict(raw_scenario.get("mutation") or {}),
                    writeback_payload=dict(raw_scenario.get("writeback-payload") or {}),
                )
            )
    return scenarios


def validate_scenarios(workflows: list[Workflow]) -> list[str]:
    errors: list[str] = []
    for scenario in load_scenarios(workflows):
        prefix = f"{scenario.workflow.metadata_path}: tests.scenarios[{scenario.id or '?'}]"
        if not SCENARIO_ID_PATTERN.match(scenario.id):
            errors.append(f"{prefix}: id must match {SCENARIO_ID_PATTERN.pattern}.")
        if not scenario.runs:
            errors.append(f"{prefix}: runs must include local, hosted, or both.")
        for runner in scenario.runs:
            if runner not in {"local", "hosted"}:
                errors.append(f"{prefix}: unsupported runner {runner!r}.")
        if not isinstance(scenario.inputs, dict):
            errors.append(f"{prefix}: inputs must be a mapping.")
        if not scenario.assertions:
            errors.append(f"{prefix}: assertions must not be empty.")
        if not scenario.mutation:
            for assertion in scenario.assertions:
                assertion_type = assertion.get("type")
                if assertion_type not in {
                    "file-exists",
                    "file-contains",
                    "workflow-output-equals",
                }:
                    errors.append(f"{prefix}: unsupported assertion type {assertion_type!r}.")
                if assertion_type in {"file-exists", "file-contains"} and not assertion.get("path"):
                    errors.append(f"{prefix}: {assertion_type} assertions require path.")
                if assertion_type == "file-contains" and "text" not in assertion:
                    errors.append(f"{prefix}: file-contains assertions require text.")
                if assertion_type == "workflow-output-equals":
                    if not assertion.get("name"):
                        errors.append(f"{prefix}: workflow-output-equals assertions require name.")
                    if "value" not in assertion:
                        errors.append(f"{prefix}: workflow-output-equals assertions require value.")
        if "hosted" in scenario.runs and _has_file_assertions(scenario) and not scenario.artifact:
            errors.append(f"{prefix}: hosted file assertions require artifact metadata.")
        if scenario.artifact and not scenario.artifact.get("name"):
            errors.append(f"{prefix}: artifact metadata requires name.")
        if scenario.setup_artifact:
            if "hosted" not in scenario.runs:
                errors.append(f"{prefix}: setup-artifact is supported for hosted scenarios.")
            if not scenario.setup_artifact.get("name"):
                errors.append(f"{prefix}: setup-artifact requires name.")
            if not scenario.setup_artifact.get("path"):
                errors.append(f"{prefix}: setup-artifact requires path.")
            files = scenario.setup_artifact.get("files")
            if not isinstance(files, list) or not files:
                errors.append(f"{prefix}: setup-artifact requires a nonempty files list.")
            else:
                for index, file_item in enumerate(files):
                    if not isinstance(file_item, dict) or not file_item.get("path"):
                        errors.append(f"{prefix}: setup-artifact.files[{index}] requires path.")
        if scenario.mutation:
            if "hosted" not in scenario.runs:
                errors.append(f"{prefix}: mutation is supported for hosted scenarios.")
            if scenario.mutation.get("type") != "ephemeral-branch":
                errors.append(f"{prefix}: mutation.type must be ephemeral-branch.")
            if not scenario.mutation.get("fixture-path"):
                errors.append(f"{prefix}: mutation.fixture-path is required.")
            if not scenario.mutation.get("branch-prefix"):
                errors.append(f"{prefix}: mutation.branch-prefix is required.")
            if not isinstance(scenario.mutation.get("initial-files"), list):
                errors.append(f"{prefix}: mutation.initial-files must be a list.")
            if scenario.workflow.id != "writeback":
                errors.append(
                    f"{prefix}: mutation scenarios are currently supported for writeback."
                )
            if not scenario.writeback_payload:
                errors.append(f"{prefix}: mutation scenarios require writeback-payload.")
        if scenario.writeback_payload:
            if not scenario.mutation:
                errors.append(f"{prefix}: writeback-payload requires mutation.")
            if not scenario.writeback_payload.get("artifact-name"):
                errors.append(f"{prefix}: writeback-payload.artifact-name is required.")
            if not isinstance(scenario.writeback_payload.get("files"), list):
                errors.append(f"{prefix}: writeback-payload.files must be a list.")
            if not isinstance(scenario.writeback_payload.get("paths"), list):
                errors.append(f"{prefix}: writeback-payload.paths must be a list.")
            if not isinstance(scenario.writeback_payload.get("delete-paths", []), list):
                errors.append(f"{prefix}: writeback-payload.delete-paths must be a list.")
        if scenario.mutation:
            for assertion in scenario.assertions:
                assertion_type = assertion.get("type")
                if assertion_type in {"branch-file-contains", "branch-file-missing"}:
                    if not assertion.get("path"):
                        errors.append(f"{prefix}: {assertion_type} assertions require path.")
                elif assertion_type == "latest-commit-message-equals":
                    if "value" not in assertion:
                        errors.append(
                            f"{prefix}: latest-commit-message-equals assertions require value."
                        )
                else:
                    errors.append(
                        f"{prefix}: mutation scenario assertion type "
                        f"{assertion_type!r} is unsupported."
                    )
    return errors


def write_generated_test_workflows(workflows: list[Workflow], *, check: bool = False) -> list[Path]:
    scenarios = load_scenarios(workflows)
    outputs = {
        GENERATED_HOSTED_PATH: render_test_workflow(
            scenarios, runner="hosted", name="DevFlows Hosted Scenario Tests"
        ),
        GENERATED_LOCAL_PATH: render_test_workflow(
            scenarios, runner="local", name="DevFlows Local Scenario Tests"
        ),
    }
    outputs.update(
        {GENERATED_SCRIPT_DIR / name: content for name, content in SCENARIO_SCRIPTS.items()}
    )
    changed: list[Path] = []
    for path, content in outputs.items():
        normalized = content.rstrip() + "\n"
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing != normalized:
            changed.append(path)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(normalized, encoding="utf-8")
    return changed


def render_test_workflow(scenarios: list[Scenario], *, runner: str, name: str) -> str:
    selected = [scenario for scenario in scenarios if runner in scenario.runs]
    workflow: dict[str, Any] = {
        "name": name,
        "on": _on_block(runner),
        "permissions": {"contents": "read"},
        "jobs": {},
    }
    if runner == "hosted":
        workflow["permissions"]["actions"] = "read"
    jobs = workflow["jobs"]
    for scenario in selected:
        if runner == "hosted" and scenario.mutation:
            setup_job_id = f"{scenario.job_prefix}_setup"
            call_job_id = f"{scenario.job_prefix}_call"
            assert_job_id = f"{scenario.job_prefix}_assert"
            jobs[setup_job_id] = _ephemeral_branch_setup_job(scenario)
            jobs[call_job_id] = _call_job(scenario, runner=runner)
            jobs[call_job_id]["needs"] = setup_job_id
            jobs[call_job_id]["if"] = "github.event_name != 'pull_request'"
            jobs[assert_job_id] = _assert_job(scenario, runner=runner)
            jobs[f"{scenario.job_prefix}_cleanup"] = _ephemeral_branch_cleanup_job(scenario)
            continue
        if runner == "local" and scenario.cleanup:
            jobs[f"{scenario.job_prefix}_clean"] = _cleanup_job(scenario)
        if runner == "hosted" and scenario.setup_artifact:
            jobs[f"{scenario.job_prefix}_setup"] = _setup_artifact_job(scenario)
        call_job_id = f"{scenario.job_prefix}_call"
        jobs[call_job_id] = _call_job(scenario, runner=runner)
        needs = []
        if runner == "local" and scenario.cleanup:
            needs.append(f"{scenario.job_prefix}_clean")
        if runner == "hosted" and scenario.setup_artifact:
            needs.append(f"{scenario.job_prefix}_setup")
        if needs:
            jobs[call_job_id]["needs"] = needs[0] if len(needs) == 1 else needs
        jobs[f"{scenario.job_prefix}_assert"] = _assert_job(scenario, runner=runner)
    if not selected:
        jobs["no_scenarios"] = {
            "name": "No scenarios",
            "runs-on": "ubuntu-latest",
            "steps": [
                {"name": "No scenarios registered", "run": "echo 'No scenarios registered.'"}
            ],
        }
    return dump_yaml(workflow)


def run_local_scenarios(workflows: list[Workflow]) -> int:
    write_generated_test_workflows(workflows)
    _cleanup_local_outputs(load_scenarios(workflows))
    command = [
        "act",
        "workflow_dispatch",
        "--workflows",
        str(GENERATED_LOCAL_PATH),
        "--eventpath",
        str(LOCAL_EVENT_PATH),
        "--bind",
        "-P",
        ACT_PLATFORM,
    ]
    return subprocess.run(command, check=False).returncode


def _on_block(runner: str) -> dict[str, Any]:
    if runner == "hosted":
        return {
            "pull_request": None,
            "push": {"branches": ["main"]},
            "workflow_dispatch": None,
        }
    return {"workflow_dispatch": None}


def _cleanup_job(scenario: Scenario) -> dict[str, Any]:
    script = "rm -rf " + " ".join(shlex.quote(path) for path in scenario.cleanup)
    return {
        "name": f"{scenario.workflow.name}: {scenario.name} cleanup",
        "runs-on": "ubuntu-latest",
        "steps": [{"name": "Remove previous scenario outputs", "run": script}],
    }


def _setup_artifact_job(scenario: Scenario) -> dict[str, Any]:
    return {
        "name": f"{scenario.workflow.name}: {scenario.name} setup",
        "runs-on": "ubuntu-latest",
        "steps": [
            {
                "name": "Create setup files",
                "shell": "bash",
                "env": {
                    "DEVFLOWS_SETUP_FILES": json.dumps(
                        scenario.setup_artifact.get("files", []), indent=2
                    )
                },
                "run": f"python {GENERATED_SCRIPT_DIR / 'create-setup-files.py'}",
            },
            {
                "name": "Upload setup artifact",
                "uses": UPLOAD_ARTIFACT_REF,
                "with": {
                    "name": scenario.setup_artifact["name"],
                    "path": scenario.setup_artifact["path"],
                    "if-no-files-found": "error",
                    "retention-days": 1,
                    "overwrite": True,
                },
            },
        ],
    }


def _ephemeral_branch_setup_job(scenario: Scenario) -> dict[str, Any]:
    return {
        "name": f"{scenario.workflow.name}: {scenario.name} setup",
        "runs-on": "ubuntu-latest",
        "if": "github.event_name != 'pull_request'",
        "permissions": {"contents": "write"},
        "outputs": {
            "artifact-name": "${{ steps.setup.outputs.artifact-name }}",
            "base-sha": "${{ steps.setup.outputs.base-sha }}",
            "branch": "${{ steps.setup.outputs.branch }}",
        },
        "steps": [
            {
                "name": "Checkout target repository",
                "uses": CHECKOUT_REF,
                "with": {"persist-credentials": True},
            },
            {
                "name": "Prepare branch and writeback payload",
                "id": "setup",
                "shell": "bash",
                "env": {
                    "DEVFLOWS_ARTIFACT_NAME": scenario.writeback_payload["artifact-name"],
                    "DEVFLOWS_BRANCH_PREFIX": scenario.mutation["branch-prefix"],
                    "DEVFLOWS_DELETE_PATHS": json.dumps(
                        scenario.writeback_payload.get("delete-paths", []), indent=2
                    ),
                    "DEVFLOWS_FIXTURE_PATH": scenario.mutation["fixture-path"],
                    "DEVFLOWS_INITIAL_FILES": json.dumps(
                        scenario.mutation.get("initial-files", []), indent=2
                    ),
                    "DEVFLOWS_PAYLOAD_FILES": json.dumps(
                        scenario.writeback_payload.get("files", []), indent=2
                    ),
                    "DEVFLOWS_PAYLOAD_PATHS": json.dumps(
                        scenario.writeback_payload.get("paths", []), indent=2
                    ),
                },
                "run": f"python {GENERATED_SCRIPT_DIR / 'setup-ephemeral-writeback.py'}",
            },
            {
                "name": "Upload writeback payload",
                "uses": UPLOAD_ARTIFACT_REF,
                "with": {
                    "name": "${{ steps.setup.outputs.artifact-name }}",
                    "path": ".devflows-writeback/payload",
                    "if-no-files-found": "error",
                    "retention-days": 1,
                    "overwrite": True,
                },
            },
        ],
    }


def _call_job(scenario: Scenario, *, runner: str) -> dict[str, Any]:
    job = {
        "name": f"{scenario.workflow.name}: {scenario.name}",
        "uses": f"./.github/workflows/{scenario.workflow.id}.yaml",
        "with": scenario.inputs,
    }
    if runner == "hosted" and scenario.mutation:
        setup_job_id = f"{scenario.job_prefix}_setup"
        job["permissions"] = {"actions": "read", "contents": "write"}
        job["with"] = {
            **scenario.inputs,
            "commit-branch": f"${{{{ needs.{setup_job_id}.outputs.branch }}}}",
            "commit-expected-base-sha": f"${{{{ needs.{setup_job_id}.outputs.base-sha }}}}",
            "commit-repository": "${{ github.repository }}",
            "writeback-artifact-name": f"${{{{ needs.{setup_job_id}.outputs.artifact-name }}}}",
        }
    return job


def _assert_job(scenario: Scenario, *, runner: str) -> dict[str, Any]:
    call_job_id = f"{scenario.job_prefix}_call"
    if runner == "hosted" and scenario.mutation:
        setup_job_id = f"{scenario.job_prefix}_setup"
        steps: list[dict[str, Any]] = [
            {
                "name": "Assert scenario succeeded",
                "shell": "bash",
                "env": {"ACTUAL_RESULT": f"${{{{ needs.{call_job_id}.result }}}}"},
                "run": f"python {GENERATED_SCRIPT_DIR / 'assert-result.py'}",
            },
            {
                "name": "Checkout ephemeral branch",
                "uses": CHECKOUT_REF,
                "with": {
                    "persist-credentials": False,
                    "ref": f"${{{{ needs.{setup_job_id}.outputs.branch }}}}",
                },
            },
            {
                "name": "Assert ephemeral branch",
                "shell": "bash",
                "env": {
                    "DEVFLOWS_ASSERTIONS": json.dumps(scenario.assertions, indent=2),
                    "DEVFLOWS_FIXTURE_PATH": scenario.mutation["fixture-path"],
                },
                "run": f"python {GENERATED_SCRIPT_DIR / 'assert-ephemeral-writeback.py'}",
            },
        ]
        return {
            "name": f"{scenario.workflow.name}: {scenario.name} assertions",
            "runs-on": "ubuntu-latest",
            "needs": [setup_job_id, call_job_id],
            "if": "always() && github.event_name != 'pull_request'",
            "steps": steps,
        }

    steps: list[dict[str, Any]] = [
        {
            "name": "Assert scenario succeeded",
            "shell": "bash",
            "env": {"ACTUAL_RESULT": f"${{{{ needs.{call_job_id}.result }}}}"},
            "run": f"python {GENERATED_SCRIPT_DIR / 'assert-result.py'}",
        }
    ]
    if runner == "hosted" and scenario.artifact:
        download_path = str(
            scenario.artifact.get("path") or f".devflows-test-artifacts/{scenario.id}"
        )
        steps.append(
            {
                "name": "Download scenario artifact",
                "uses": DOWNLOAD_ARTIFACT_REF,
                "with": {
                    "name": scenario.artifact["name"],
                    "path": download_path,
                },
            }
        )
    for assertion in scenario.assertions:
        steps.extend(_assertion_steps(scenario, assertion, runner=runner))
    return {
        "name": f"{scenario.workflow.name}: {scenario.name} assertions",
        "runs-on": "ubuntu-latest",
        "needs": call_job_id,
        "if": "always()",
        "steps": steps,
    }


def _ephemeral_branch_cleanup_job(scenario: Scenario) -> dict[str, Any]:
    setup_job_id = f"{scenario.job_prefix}_setup"
    call_job_id = f"{scenario.job_prefix}_call"
    assert_job_id = f"{scenario.job_prefix}_assert"
    return {
        "name": f"{scenario.workflow.name}: {scenario.name} cleanup",
        "runs-on": "ubuntu-latest",
        "needs": [setup_job_id, call_job_id, assert_job_id],
        "if": "always() && github.event_name != 'pull_request'",
        "permissions": {"contents": "write"},
        "steps": [
            {
                "name": "Checkout target repository",
                "uses": CHECKOUT_REF,
                "with": {"persist-credentials": True},
            },
            {
                "name": "Delete ephemeral branch",
                "shell": "bash",
                "env": {"DEVFLOWS_BRANCH": f"${{{{ needs.{setup_job_id}.outputs.branch }}}}"},
                "run": f"python {GENERATED_SCRIPT_DIR / 'cleanup-ephemeral-branch.py'}",
            },
        ],
    }


def _assertion_steps(
    scenario: Scenario, assertion: dict[str, Any], *, runner: str
) -> list[dict[str, Any]]:
    assertion_type = assertion["type"]
    if assertion_type == "workflow-output-equals":
        output_name = str(assertion["name"])
        call_job_id = f"{scenario.job_prefix}_call"
        return [
            {
                "name": f"Assert output {output_name}",
                "shell": "bash",
                "env": {
                    "ASSERT_NAME": output_name,
                    "EXPECTED": str(assertion["value"]),
                    "ACTUAL": f"${{{{ needs.{call_job_id}.outputs.{output_name} }}}}",
                },
                "run": f"python {GENERATED_SCRIPT_DIR / 'assert-equals.py'}",
            }
        ]
    path = _assertion_path(scenario, assertion, runner=runner)
    if assertion_type == "file-exists":
        return [
            {
                "name": f"Assert file exists: {assertion['path']}",
                "shell": "bash",
                "env": {"ASSERT_PATH": path},
                "run": f"python {GENERATED_SCRIPT_DIR / 'assert-file-exists.py'}",
            }
        ]
    return [
        {
            "name": f"Assert file contains: {assertion['path']}",
            "shell": "bash",
            "env": {"ASSERT_PATH": path, "ASSERT_TEXT": str(assertion["text"])},
            "run": f"python {GENERATED_SCRIPT_DIR / 'assert-file-contains.py'}",
        }
    ]


def _assertion_path(scenario: Scenario, assertion: dict[str, Any], *, runner: str) -> str:
    path = str(assertion["path"])
    if runner == "hosted" and scenario.artifact:
        download_path = str(
            scenario.artifact.get("path") or f".devflows-test-artifacts/{scenario.id}"
        )
        return str(Path(download_path) / path)
    return path


def _cleanup_local_outputs(scenarios: list[Scenario]) -> None:
    for scenario in scenarios:
        if "local" not in scenario.runs:
            continue
        for path in scenario.cleanup:
            target = Path(path)
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()


def _has_file_assertions(scenario: Scenario) -> bool:
    return any(
        assertion.get("type") in {"file-exists", "file-contains"}
        for assertion in scenario.assertions
    )
