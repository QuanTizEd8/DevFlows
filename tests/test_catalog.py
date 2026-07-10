from pathlib import Path

from devflows.catalog import load_catalog, validate_workflow


def test_catalog_loads_active_workflows() -> None:
    workflows = load_catalog()
    workflows_by_id = {item.id: item for item in workflows}

    assert [item.id for item in workflows] == [
        "build-devcontainer",
        "docs-build",
        "pandoc",
        "python-build",
        "python-lint",
        "python-test",
        "writeback",
    ]
    assert (
        workflows_by_id["pandoc"].workflow_call["inputs"]["pandoc-image"]["default"]
        == "pandoc/latex:3-ubuntu"
    )
    assert (
        workflows_by_id["build-devcontainer"].workflow_call["inputs"]["image-name"]["required"]
        is True
    )
    assert (
        workflows_by_id["writeback"].workflow_call["inputs"]["writeback-artifact-name"]["type"]
        == "string"
    )


def test_active_workflows_are_valid() -> None:
    errors = []
    for item in load_catalog():
        errors.extend(validate_workflow(item))

    assert errors == []


def test_drafts_are_not_loaded_by_default() -> None:
    assert all("_drafts" not in item.path.parts for item in load_catalog())


def test_published_path_uses_required_github_location() -> None:
    workflow = {item.id: item for item in load_catalog()}["pandoc"]

    assert workflow.published_path == Path(".github/workflows/pandoc.yaml")
