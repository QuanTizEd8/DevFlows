from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devflows.yaml import load_yaml

CATALOG_DIR = Path("workflows")
PUBLISHED_DIR = Path(".github/workflows")


@dataclass(frozen=True)
class Workflow:
    id: str
    path: Path
    workflow_path: Path
    metadata_path: Path
    metadata: dict[str, Any]
    workflow: dict[str, Any]

    @property
    def published_path(self) -> Path:
        return PUBLISHED_DIR / f"{self.id}.yaml"

    @property
    def name(self) -> str:
        return str(self.metadata.get("name") or self.workflow.get("name") or self.id)

    @property
    def summary(self) -> str:
        return str(self.metadata.get("summary") or "")

    @property
    def status(self) -> str:
        return str(self.metadata.get("status") or "active")

    @property
    def workflow_call(self) -> dict[str, Any]:
        on_block = self.workflow.get("on") or {}
        if not isinstance(on_block, dict):
            return {}
        workflow_call = on_block.get("workflow_call") or {}
        return workflow_call if isinstance(workflow_call, dict) else {}


def workflow_dirs(root: Path = CATALOG_DIR, *, include_drafts: bool = False) -> list[Path]:
    if not root.exists():
        return []
    dirs: list[Path] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        if path.name.startswith("_") and not include_drafts:
            continue
        if path.name == "_drafts":
            if include_drafts:
                dirs.extend(sorted(item for item in path.iterdir() if item.is_dir()))
            continue
        dirs.append(path)
    return dirs


def load_workflow(path: Path) -> Workflow:
    workflow_path = path / "workflow.yaml"
    metadata_path = path / "devflow.yaml"
    if not workflow_path.exists():
        raise ValueError(f"{path} is missing workflow.yaml.")
    if not metadata_path.exists():
        raise ValueError(f"{path} is missing devflow.yaml.")
    metadata = load_yaml(metadata_path)
    workflow = load_yaml(workflow_path)
    workflow_id = str(metadata.get("id") or path.name)
    return Workflow(
        id=workflow_id,
        path=path,
        workflow_path=workflow_path,
        metadata_path=metadata_path,
        metadata=metadata,
        workflow=workflow,
    )


def load_catalog(root: Path = CATALOG_DIR, *, include_drafts: bool = False) -> list[Workflow]:
    return [load_workflow(path) for path in workflow_dirs(root, include_drafts=include_drafts)]


def validate_workflow(item: Workflow) -> list[str]:
    errors: list[str] = []
    if item.id != item.path.name:
        errors.append(f"{item.path}: metadata id {item.id!r} must match directory name.")
    if item.metadata.get("status") not in {"active", "deprecated", "experimental"}:
        errors.append(f"{item.metadata_path}: status must be active, deprecated, or experimental.")
    if not item.workflow.get("name"):
        errors.append(f"{item.workflow_path}: workflow must define name.")
    if not item.workflow_call:
        errors.append(f"{item.workflow_path}: reusable workflows must define on.workflow_call.")
    if "release" not in item.metadata:
        errors.append(f"{item.metadata_path}: release configuration is required.")
    return errors
