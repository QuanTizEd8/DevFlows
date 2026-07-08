from devflows.catalog import load_catalog
from devflows.publish import build_published_workflow, render_published_workflow


def test_pandoc_source_workflow_only_declares_domain_inputs() -> None:
    pandoc = load_catalog()[0]
    source_inputs = pandoc.workflow_call["inputs"]

    assert list(source_inputs) == [
        "pandoc-arguments",
        "pandoc-image",
        "pandoc-working-directory",
    ]
    assert "checkout-enabled" not in source_inputs
    assert "artifact-upload-enabled" not in source_inputs
    assert "commit-enabled" not in source_inputs


def test_pandoc_published_workflow_injects_shared_io_interface() -> None:
    pandoc = load_catalog()[0]
    workflow = build_published_workflow(pandoc)
    inputs = workflow["on"]["workflow_call"]["inputs"]
    secrets = workflow["on"]["workflow_call"]["secrets"]

    assert inputs["checkout-enabled"]["default"] is True
    assert inputs["artifact-download-enabled"]["default"] is False
    assert inputs["artifact-upload-enabled"]["default"] is False
    assert inputs["commit-enabled"]["default"] is False
    assert inputs["commit-internal-artifact-name"]["default"] == "devflows-pandoc-writeback"
    assert "checkout-token" in secrets
    assert "artifact-download-token" in secrets
    assert "commit-token" in secrets


def test_pandoc_published_workflow_injects_shared_io_steps_and_commit_job() -> None:
    pandoc = load_catalog()[0]
    workflow = build_published_workflow(pandoc)
    steps = workflow["jobs"]["pandoc"]["steps"]

    assert [step["name"] for step in steps] == [
        "Checkout repository",
        "Download artifacts",
        "Resolve DevFlows runtime",
        "Checkout DevFlows runtime",
        "Run Pandoc",
        "Upload artifact",
        "Create writeback payload",
        "Upload writeback payload",
    ]
    assert workflow["jobs"]["commit"]["uses"] == "./.github/workflows/writeback.yaml"
    assert workflow["jobs"]["commit"]["needs"] == "pandoc"


def test_explicit_workflows_publish_as_source_copies() -> None:
    writeback = load_catalog()[1]

    assert render_published_workflow(writeback) == writeback.workflow_path.read_text(
        encoding="utf-8"
    )
