from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from devflows.catalog import Workflow
from devflows.yaml import dump_yaml

CHECKOUT_REF = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
DOWNLOAD_ARTIFACT_REF = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
UPLOAD_ARTIFACT_REF = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def render_published_workflow(item: Workflow) -> str:
    if not _io_config(item):
        return item.workflow_path.read_text(encoding="utf-8")
    return dump_yaml(build_published_workflow(item))


def build_published_workflow(item: Workflow) -> dict[str, Any]:
    workflow = deepcopy(item.workflow)
    io_config = _io_config(item)
    if not io_config:
        return workflow

    workflow_call = _workflow_call(workflow)
    inputs = workflow_call.setdefault("inputs", {})
    secrets = workflow_call.setdefault("secrets", {})

    if _enabled(io_config, "checkout"):
        inputs.update(deepcopy(CHECKOUT_INPUTS))
        secrets.update(deepcopy(CHECKOUT_SECRETS))
    if _enabled(io_config, "artifact-download"):
        inputs.update(deepcopy(ARTIFACT_DOWNLOAD_INPUTS))
        secrets.update(deepcopy(ARTIFACT_DOWNLOAD_SECRETS))
    if _enabled(io_config, "artifact-upload"):
        inputs.update(deepcopy(ARTIFACT_UPLOAD_INPUTS))
    if _enabled(io_config, "writeback"):
        inputs.update(deepcopy(COMMIT_INPUTS))
        inputs["commit-internal-artifact-name"]["default"] = f"devflows-{item.id}-writeback"
        secrets.update(deepcopy(COMMIT_SECRETS))

    job_id = str(io_config.get("job") or _first_runner_job_id(workflow))
    jobs = workflow.setdefault("jobs", {})
    if job_id not in jobs:
        raise ValueError(f"{item.metadata_path}: io.job {job_id!r} does not exist.")
    job = jobs[job_id]
    if not isinstance(job, dict) or "steps" not in job:
        raise ValueError(f"{item.metadata_path}: io.job {job_id!r} must be a runner job.")

    prefix_steps: list[dict[str, Any]] = []
    suffix_steps: list[dict[str, Any]] = []
    if _enabled(io_config, "checkout"):
        prefix_steps.append(_checkout_step())
    if _enabled(io_config, "artifact-download"):
        prefix_steps.append(_download_artifact_step())
    if _enabled(io_config, "runtime"):
        prefix_steps.extend(_runtime_steps())
    if _enabled(io_config, "artifact-upload"):
        suffix_steps.append(_upload_artifact_step())
    if _enabled(io_config, "writeback"):
        suffix_steps.extend(_create_writeback_steps())
        jobs["commit"] = _commit_job(job_id)

    job["steps"] = prefix_steps + list(job.get("steps", [])) + suffix_steps
    _ensure_job_permissions(
        job,
        contents="read",
        actions="read"
        if any(
            _enabled(io_config, channel)
            for channel in ("artifact-download", "artifact-upload", "writeback")
        )
        else None,
    )
    return workflow


def validate_publish_config(item: Workflow) -> list[str]:
    errors: list[str] = []
    config = _io_config(item)
    if not config:
        return errors
    supported = {
        "artifact-download",
        "artifact-upload",
        "checkout",
        "job",
        "runtime",
        "writeback",
    }
    for key in config:
        if key not in supported:
            errors.append(f"{item.metadata_path}: io.{key} is not supported.")
    if _enabled(config, "writeback") and not _enabled(config, "runtime"):
        errors.append(f"{item.metadata_path}: io.writeback requires io.runtime.")
    job_id = str(config.get("job") or "")
    jobs = item.workflow.get("jobs") or {}
    if job_id:
        job = jobs.get(job_id)
        if not isinstance(job, dict) or "steps" not in job:
            errors.append(f"{item.metadata_path}: io.job {job_id!r} must be a runner job.")
    elif not any(isinstance(job, dict) and "steps" in job for job in jobs.values()):
        errors.append(f"{item.metadata_path}: io requires at least one runner job.")
    return errors


def published_workflow_call(item: Workflow) -> dict[str, Any]:
    workflow_call = _workflow_call(build_published_workflow(item))
    return workflow_call if isinstance(workflow_call, dict) else {}


def write_published_workflow(path: Path, item: Workflow) -> None:
    path.write_text(render_published_workflow(item).rstrip() + "\n", encoding="utf-8")


def _workflow_call(workflow: dict[str, Any]) -> dict[str, Any]:
    on_block = workflow.setdefault("on", {})
    if not isinstance(on_block, dict):
        raise ValueError("workflow on block must be a mapping.")
    workflow_call = on_block.setdefault("workflow_call", {})
    if not isinstance(workflow_call, dict):
        raise ValueError("workflow_call block must be a mapping.")
    return workflow_call


def _io_config(item: Workflow) -> dict[str, Any]:
    config = item.metadata.get("io") or {}
    if config is True:
        return {"checkout": True, "artifact-download": True, "artifact-upload": True}
    if not isinstance(config, dict):
        return {}
    return config


def _enabled(config: dict[str, Any], name: str) -> bool:
    return bool(config.get(name))


def _first_runner_job_id(workflow: dict[str, Any]) -> str:
    jobs = workflow.get("jobs") or {}
    for job_id, job in jobs.items():
        if isinstance(job, dict) and "steps" in job:
            return str(job_id)
    raise ValueError("workflow must contain at least one runner job for IO injection.")


def _ensure_job_permissions(job: dict[str, Any], **permissions: str | None) -> None:
    current = job.setdefault("permissions", {})
    if current is None:
        current = {}
        job["permissions"] = current
    if not isinstance(current, dict):
        return
    for name, level in permissions.items():
        if level is not None and name not in current:
            current[name] = level


def _checkout_step() -> dict[str, Any]:
    return {
        "name": "Checkout repository",
        "if": "inputs.checkout-enabled",
        "uses": CHECKOUT_REF,
        "with": {
            "repository": "${{ inputs.checkout-repository }}",
            "ref": "${{ inputs.checkout-ref }}",
            "token": "${{ secrets.checkout-token || github.token }}",
            "ssh-key": "${{ secrets.checkout-ssh-key }}",
            "ssh-known-hosts": "${{ inputs.checkout-ssh-known-hosts }}",
            "ssh-strict": "${{ inputs.checkout-ssh-strict }}",
            "ssh-user": "${{ inputs.checkout-ssh-user }}",
            "persist-credentials": "${{ inputs.checkout-persist-credentials }}",
            "path": "${{ inputs.checkout-path }}",
            "clean": "${{ inputs.checkout-clean }}",
            "filter": "${{ inputs.checkout-filter }}",
            "sparse-checkout": "${{ inputs.checkout-sparse-checkout }}",
            "sparse-checkout-cone-mode": "${{ inputs.checkout-sparse-checkout-cone-mode }}",
            "fetch-depth": "${{ inputs.checkout-fetch-depth }}",
            "fetch-tags": "${{ inputs.checkout-fetch-tags }}",
            "show-progress": "${{ inputs.checkout-show-progress }}",
            "lfs": "${{ inputs.checkout-lfs }}",
            "submodules": "${{ inputs.checkout-submodules }}",
            "set-safe-directory": "${{ inputs.checkout-set-safe-directory }}",
            "github-server-url": "${{ inputs.checkout-github-server-url }}",
            "allow-unsafe-pr-checkout": "${{ inputs.checkout-allow-unsafe-pr-checkout }}",
        },
    }


def _download_artifact_step() -> dict[str, Any]:
    return {
        "name": "Download artifacts",
        "if": "inputs.artifact-download-enabled",
        "uses": DOWNLOAD_ARTIFACT_REF,
        "with": {
            "name": "${{ inputs.artifact-download-name }}",
            "artifact-ids": "${{ inputs.artifact-download-ids }}",
            "path": "${{ inputs.artifact-download-path }}",
            "pattern": "${{ inputs.artifact-download-pattern }}",
            "merge-multiple": "${{ inputs.artifact-download-merge-multiple }}",
            "github-token": "${{ secrets.artifact-download-token }}",
            "repository": "${{ inputs.artifact-download-repository }}",
            "run-id": "${{ inputs.artifact-download-run-id }}",
            "skip-decompress": "${{ inputs.artifact-download-skip-decompress }}",
            "digest-mismatch": "${{ inputs.artifact-download-digest-mismatch }}",
        },
    }


def _runtime_steps() -> list[dict[str, Any]]:
    return [
        {
            "name": "Resolve DevFlows runtime",
            "id": "devflows-runtime",
            "shell": "bash",
            "env": {"DEVFLOWS_WORKFLOW_REF": "${{ github.workflow_ref }}"},
            "run": (
                'if [ -z "${DEVFLOWS_WORKFLOW_REF}" ]; then\n'
                '  echo "script-root=.github/workflows"\n'
                "else\n"
                '  echo "repository=${DEVFLOWS_WORKFLOW_REF%%/.github/workflows/*}"\n'
                '  echo "ref=${DEVFLOWS_WORKFLOW_REF##*@}"\n'
                '  echo "script-root=.devflows-runtime/.github/workflows"\n'
                'fi >> "$GITHUB_OUTPUT"'
            ),
        },
        {
            "name": "Checkout DevFlows runtime",
            "if": "steps.devflows-runtime.outputs.repository != ''",
            "uses": CHECKOUT_REF,
            "with": {
                "repository": "${{ steps.devflows-runtime.outputs.repository }}",
                "ref": "${{ steps.devflows-runtime.outputs.ref }}",
                "token": "${{ github.token }}",
                "path": ".devflows-runtime",
                "persist-credentials": False,
            },
        },
    ]


def _upload_artifact_step() -> dict[str, Any]:
    return {
        "name": "Upload artifact",
        "if": "inputs.artifact-upload-enabled && inputs.artifact-upload-path != ''",
        "uses": UPLOAD_ARTIFACT_REF,
        "with": {
            "name": "${{ inputs.artifact-upload-name }}",
            "path": "${{ inputs.artifact-upload-path }}",
            "if-no-files-found": "${{ inputs.artifact-upload-if-no-files-found }}",
            "retention-days": "${{ inputs.artifact-upload-retention-days }}",
            "compression-level": "${{ inputs.artifact-upload-compression-level }}",
            "overwrite": "${{ inputs.artifact-upload-overwrite }}",
            "include-hidden-files": "${{ inputs.artifact-upload-include-hidden-files }}",
            "archive": "${{ inputs.artifact-upload-archive }}",
        },
    }


def _create_writeback_steps() -> list[dict[str, Any]]:
    return [
        {
            "name": "Create writeback payload",
            "if": "inputs.commit-enabled",
            "env": {
                "DEVFLOWS_SCRIPT_ROOT": "${{ steps.devflows-runtime.outputs.script-root }}",
                "WRITEBACK_DELETE_PATHS": "${{ inputs.commit-delete-paths }}",
                "WRITEBACK_PATHS": "${{ inputs.commit-paths }}",
                "WRITEBACK_PAYLOAD_DIR": ".devflows-writeback/payload",
                "WRITEBACK_SOURCE_REF": "${{ github.ref }}",
                "WRITEBACK_SOURCE_REPOSITORY": "${{ github.repository }}",
                "WRITEBACK_SOURCE_SHA": "${{ github.sha }}",
            },
            "shell": "bash",
            "run": 'python "${DEVFLOWS_SCRIPT_ROOT}/writeback/create-payload.py"',
        },
        {
            "name": "Upload writeback payload",
            "if": "inputs.commit-enabled",
            "uses": UPLOAD_ARTIFACT_REF,
            "with": {
                "name": "${{ inputs.commit-internal-artifact-name }}",
                "path": ".devflows-writeback/payload",
                "if-no-files-found": "error",
                "retention-days": 1,
                "compression-level": 0,
                "overwrite": True,
                "include-hidden-files": True,
            },
        },
    ]


def _commit_job(needs: str) -> dict[str, Any]:
    return {
        "name": "Commit generated files",
        "needs": needs,
        "if": "inputs.commit-enabled",
        "uses": "./.github/workflows/writeback.yaml",
        "permissions": {"actions": "read", "contents": "write"},
        "with": {
            "writeback-artifact-name": "${{ inputs.commit-internal-artifact-name }}",
            "commit-repository": "${{ inputs.commit-repository }}",
            "commit-branch": "${{ inputs.commit-branch }}",
            "commit-message": "${{ inputs.commit-message }}",
            "commit-author-name": "${{ inputs.commit-author-name }}",
            "commit-author-email": "${{ inputs.commit-author-email }}",
            "commit-push": "${{ inputs.commit-push }}",
            "commit-expected-base-sha": "${{ inputs.commit-expected-base-sha }}",
        },
        "secrets": {"commit-token": "${{ secrets.commit-token }}"},
    }


CHECKOUT_INPUTS: dict[str, dict[str, Any]] = {
    "checkout-enabled": {
        "description": "Whether to run actions/checkout before workflow execution.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
    "checkout-repository": {
        "description": "Repository name with owner to checkout.",
        "type": "string",
        "required": False,
        "default": "${{ github.repository }}",
    },
    "checkout-ref": {
        "description": "Branch, tag, or SHA to checkout.",
        "type": "string",
        "required": False,
        "default": "${{ github.ref }}",
    },
    "checkout-ssh-known-hosts": {
        "description": "Known hosts in addition to the user and global host key database.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "checkout-ssh-strict": {
        "description": "Whether to perform strict host key checking.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
    "checkout-ssh-user": {
        "description": "SSH user to use when connecting to the remote SSH host.",
        "type": "string",
        "required": False,
        "default": "git",
    },
    "checkout-persist-credentials": {
        "description": "Whether to configure the token or SSH key with local git config.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
    "checkout-path": {
        "description": "Relative path under GITHUB_WORKSPACE to place the repository.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "checkout-clean": {
        "description": "Whether to clean and reset before fetching.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
    "checkout-filter": {
        "description": "Partial clone filter. Overrides sparse checkout when set.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "checkout-sparse-checkout": {
        "description": "Sparse checkout patterns separated by new lines.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "checkout-sparse-checkout-cone-mode": {
        "description": "Whether to use cone mode for sparse checkout.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
    "checkout-fetch-depth": {
        "description": "Number of commits to fetch. Use 0 for all history.",
        "type": "number",
        "required": False,
        "default": 1,
    },
    "checkout-fetch-tags": {
        "description": "Whether to fetch tags when fetch-depth is greater than 0.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "checkout-show-progress": {
        "description": "Whether to show fetch progress output.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
    "checkout-lfs": {
        "description": "Whether to download Git LFS files.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "checkout-submodules": {
        "description": "Whether to checkout submodules; use recursive for nested submodules.",
        "type": "string",
        "required": False,
        "default": "false",
    },
    "checkout-set-safe-directory": {
        "description": "Whether to add the repository path as a safe Git directory.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
    "checkout-github-server-url": {
        "description": "GitHub server URL to fetch from.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "checkout-allow-unsafe-pr-checkout": {
        "description": "Allow checkout of fork pull request code in trusted contexts.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
}

CHECKOUT_SECRETS: dict[str, dict[str, Any]] = {
    "checkout-token": {
        "description": "Token used by actions/checkout. Defaults to github.token.",
        "required": False,
    },
    "checkout-ssh-key": {
        "description": "SSH key used by actions/checkout.",
        "required": False,
    },
}

ARTIFACT_DOWNLOAD_INPUTS: dict[str, dict[str, Any]] = {
    "artifact-download-enabled": {
        "description": "Whether to download artifacts before workflow execution.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "artifact-download-name": {
        "description": "Name of the artifact to download. Leave empty to download all artifacts.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "artifact-download-ids": {
        "description": (
            "Comma-separated artifact IDs to download. Mutually exclusive with "
            "artifact-download-name."
        ),
        "type": "string",
        "required": False,
        "default": "",
    },
    "artifact-download-path": {
        "description": "Destination path for downloaded artifacts.",
        "type": "string",
        "required": False,
        "default": ".",
    },
    "artifact-download-pattern": {
        "description": "Glob pattern matching artifacts to download when name is unset.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "artifact-download-merge-multiple": {
        "description": "Whether multiple matched artifacts are extracted into one directory.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "artifact-download-repository": {
        "description": "Repository to download artifacts from when a token is set.",
        "type": "string",
        "required": False,
        "default": "${{ github.repository }}",
    },
    "artifact-download-run-id": {
        "description": "Workflow run ID to download artifacts from when a token is set.",
        "type": "string",
        "required": False,
        "default": "${{ github.run_id }}",
    },
    "artifact-download-skip-decompress": {
        "description": "Whether to download the artifact archive without extracting it.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "artifact-download-digest-mismatch": {
        "description": "Behavior when a downloaded artifact digest does not match.",
        "type": "string",
        "required": False,
        "default": "error",
    },
}

ARTIFACT_DOWNLOAD_SECRETS: dict[str, dict[str, Any]] = {
    "artifact-download-token": {
        "description": "Token used to download artifacts from another repository or run.",
        "required": False,
    },
}

ARTIFACT_UPLOAD_INPUTS: dict[str, dict[str, Any]] = {
    "artifact-upload-enabled": {
        "description": "Whether to upload artifacts after workflow execution.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "artifact-upload-path": {
        "description": "File, directory, or wildcard pattern to upload after workflow execution.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "artifact-upload-name": {
        "description": "Artifact name.",
        "type": "string",
        "required": False,
        "default": "artifact",
    },
    "artifact-upload-if-no-files-found": {
        "description": "Behavior when no files match artifact-upload-path.",
        "type": "string",
        "required": False,
        "default": "warn",
    },
    "artifact-upload-retention-days": {
        "description": "Artifact retention in days. Use 0 for repository default.",
        "type": "number",
        "required": False,
        "default": 0,
    },
    "artifact-upload-compression-level": {
        "description": "Compression level from 0 to 9.",
        "type": "number",
        "required": False,
        "default": 6,
    },
    "artifact-upload-overwrite": {
        "description": "Whether to overwrite an existing artifact with the same name.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "artifact-upload-include-hidden-files": {
        "description": "Whether hidden files under artifact-upload-path are included.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "artifact-upload-archive": {
        "description": "Whether upload-artifact archives files before upload.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
}

COMMIT_INPUTS: dict[str, dict[str, Any]] = {
    "commit-enabled": {
        "description": "Whether to commit selected generated files back to a repository.",
        "type": "boolean",
        "required": False,
        "default": False,
    },
    "commit-paths": {
        "description": "Newline-separated files or directories to include in the writeback commit.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "commit-delete-paths": {
        "description": "Newline-separated files or directories to delete in the writeback commit.",
        "type": "string",
        "required": False,
        "default": "",
    },
    "commit-message": {
        "description": "Commit message for generated file writeback.",
        "type": "string",
        "required": False,
        "default": "chore: update generated files",
    },
    "commit-repository": {
        "description": "Repository name with owner to commit to.",
        "type": "string",
        "required": False,
        "default": "${{ github.repository }}",
    },
    "commit-branch": {
        "description": "Branch to check out and push generated changes to.",
        "type": "string",
        "required": False,
        "default": "${{ github.ref_name }}",
    },
    "commit-author-name": {
        "description": "Git author name for generated file commits.",
        "type": "string",
        "required": False,
        "default": "github-actions[bot]",
    },
    "commit-author-email": {
        "description": "Git author email for generated file commits.",
        "type": "string",
        "required": False,
        "default": "41898282+github-actions[bot]@users.noreply.github.com",
    },
    "commit-push": {
        "description": "Whether to push the generated commit.",
        "type": "boolean",
        "required": False,
        "default": True,
    },
    "commit-expected-base-sha": {
        "description": (
            "Optional SHA that the writeback target branch must point to before committing."
        ),
        "type": "string",
        "required": False,
        "default": "",
    },
    "commit-internal-artifact-name": {
        "description": "Internal artifact name used to transfer the writeback payload.",
        "type": "string",
        "required": False,
        "default": "devflows-writeback",
    },
}

COMMIT_SECRETS: dict[str, dict[str, Any]] = {
    "commit-token": {
        "description": (
            "Token used by the writeback job. Must be able to write contents when "
            "commit-enabled is true."
        ),
        "required": False,
    },
}
