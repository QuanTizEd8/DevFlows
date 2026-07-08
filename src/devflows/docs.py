from __future__ import annotations

from pathlib import Path
from typing import Any

from devflows.catalog import Workflow

GENERATED_DIR = Path("docs/reference")


def render_catalog(workflows: list[Workflow]) -> str:
    lines = [
        "# Workflow Catalog",
        "",
        "This page is generated from the workflow catalog metadata.",
        "",
        "```{toctree}",
        ":maxdepth: 1",
        "",
    ]
    lines.extend(f"workflows/{item.id}" for item in workflows)
    lines.extend(["```", ""])
    return "\n".join(lines)


def render_workflow(item: Workflow) -> str:
    workflow_call = item.workflow_call
    inputs = _mapping(workflow_call.get("inputs"))
    secrets = _mapping(workflow_call.get("secrets"))
    outputs = _mapping(workflow_call.get("outputs"))
    permissions = item.workflow.get("permissions") or {}
    examples = item.metadata.get("examples") or []
    release = item.metadata.get("release") or {}
    notes = item.metadata.get("notes") or []
    scenarios = item.metadata.get("tests", {}).get("scenarios", []) or []

    lines = [
        f"# {item.name}",
        "",
        item.summary or "No summary provided.",
        "",
        "## Usage",
        "",
        "```yaml",
        "jobs:",
        f"  call-{item.id}:",
        f"    uses: owner/devflows/.github/workflows/{item.id}.yaml@{item.id}/v1",
        "```",
        "",
        "## Versioning",
        "",
        f"- Current line: `{item.id}/v{release.get('major', 1)}`",
        f"- Exact release tags use `{item.id}/vX.Y.Z`.",
        "- Commit SHAs remain the highest-assurance reference.",
        "",
        "## Inputs",
        "",
        _render_table(inputs, ["name", "type", "required", "default", "description"]),
        "",
        "## Secrets",
        "",
        _render_table(secrets, ["name", "required", "description"]),
        "",
        "## Outputs",
        "",
        _render_table(outputs, ["name", "description"]),
        "",
        "## Permissions",
        "",
        _render_permissions(permissions),
        "",
        "## Examples",
        "",
    ]
    if examples:
        for example in examples:
            title = example.get("name", "Example")
            path = example.get("path", "")
            lines.extend([f"### {title}", "", f"Source: `{path}`", ""])
            if path:
                lines.extend(["```yaml", _read_example(path), "```", ""])
    else:
        lines.append("No examples registered yet.")
        lines.append("")
    if notes:
        lines.extend(["## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    if scenarios:
        lines.extend(["## Test Scenarios", ""])
        for scenario in scenarios:
            scenario_id = scenario.get("id", "")
            scenario_name = scenario.get("name") or scenario_id
            runs = ", ".join(scenario.get("runs", []) or [])
            assertions = scenario.get("assertions", []) or []
            lines.append(
                f"- `{scenario_id}`: {scenario_name} ({runs}); {len(assertions)} assertion(s)."
            )
        lines.append("")
    return "\n".join(lines)


def write_generated_docs(
    workflows: list[Workflow],
    *,
    check: bool = False,
    output_dir: Path = GENERATED_DIR,
) -> list[Path]:
    outputs = {
        output_dir / "catalog.md": render_catalog(workflows),
        **{output_dir / "workflows" / f"{item.id}.md": render_workflow(item) for item in workflows},
    }
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


def _mapping(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    return {str(key): data if isinstance(data, dict) else {} for key, data in value.items()}


def _render_table(items: dict[str, dict[str, Any]], columns: list[str]) -> str:
    if not items:
        return "None."
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for name, data in items.items():
        row = []
        for column in columns:
            value = name if column == "name" else data.get(column, "")
            row.append(_cell(value))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _render_permissions(permissions: Any) -> str:
    if not permissions:
        return "No explicit top-level permissions declared."
    if isinstance(permissions, str):
        return f"`{permissions}`"
    if isinstance(permissions, dict):
        return "\n".join(f"- `{name}`: `{value}`" for name, value in sorted(permissions.items()))
    return str(permissions)


def _read_example(path: str) -> str:
    example_path = Path(path)
    if not example_path.exists():
        return f"# Missing example fixture: {path}"
    return example_path.read_text(encoding="utf-8").rstrip()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", "<br>")
    return text.replace("|", "\\|")
