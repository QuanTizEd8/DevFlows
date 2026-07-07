from pathlib import Path

from devflows.catalog import load_catalog, validate_workflow


def test_catalog_loads_active_workflows() -> None:
    workflows = load_catalog()

    assert [item.id for item in workflows] == ["hello-world"]
    assert workflows[0].workflow_call["inputs"]["message"]["type"] == "string"


def test_active_workflows_are_valid() -> None:
    errors = []
    for item in load_catalog():
        errors.extend(validate_workflow(item))

    assert errors == []


def test_drafts_are_not_loaded_by_default() -> None:
    assert all("_drafts" not in item.path.parts for item in load_catalog())


def test_published_path_uses_required_github_location() -> None:
    workflow = load_catalog()[0]

    assert workflow.published_path == Path(".github/workflows/hello-world.yaml")
