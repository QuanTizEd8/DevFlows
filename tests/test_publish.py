from devflows.catalog import load_catalog
from devflows.publish import build_published_workflow, render_published_workflow


def _workflow(workflow_id: str):
    return {item.id: item for item in load_catalog()}[workflow_id]


def test_pandoc_source_workflow_only_declares_domain_inputs() -> None:
    pandoc = _workflow("pandoc")
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
    pandoc = _workflow("pandoc")
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
    pandoc = _workflow("pandoc")
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
    writeback = _workflow("writeback")

    assert render_published_workflow(writeback) == writeback.workflow_path.read_text(
        encoding="utf-8"
    )


def test_build_devcontainer_source_replaces_monolithic_config() -> None:
    build_devcontainer = _workflow("build-devcontainer")
    inputs = build_devcontainer.workflow_call["inputs"]

    assert "config" not in inputs
    assert inputs["image-name"]["required"] is True
    assert "build-matrix" in inputs
    assert "prepare-command" in inputs
    assert "devcontainer-run-cmd" not in inputs
    assert "docker-registry-auth" not in inputs
    assert "cache-save-always" not in inputs


def test_build_devcontainer_published_workflow_injects_checkout_and_runtime_job() -> None:
    workflow = build_published_workflow(_workflow("build-devcontainer"))
    build_steps = workflow["jobs"]["build-devcontainer"]["steps"]
    merge_steps = workflow["jobs"]["merge-devcontainer"]["steps"]

    assert [step["name"] for step in build_steps[:6]] == [
        "Checkout repository",
        "Download artifacts",
        "Resolve DevFlows runtime",
        "Checkout DevFlows runtime",
        "Prepare workspace",
        "Resolve build settings",
    ]
    assert [step["name"] for step in merge_steps[:3]] == [
        "Resolve DevFlows runtime",
        "Checkout DevFlows runtime",
        "Docker login",
    ]


def test_build_devcontainer_published_workflow_filters_conflicting_action_inputs() -> None:
    rendered = render_published_workflow(_workflow("build-devcontainer"))

    assert "fromJSON(inputs.config)" not in rendered
    assert "runCmd:" not in rendered
    assert "subFolder:" not in rendered
    assert "inheritEnv:" not in rendered
    assert "skipContainerUserIdUpdate:" not in rendered
    assert "registry-auth:" not in rendered
    assert "save-always:" not in rendered
    assert "docker/login-action@af1e73f918a031802d376d3c8bbc3fe56130a9b0" in rendered
    assert "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c" in rendered
    assert "devcontainers/ci@513af61f4de4f75d37e4438f184ba4358f0fc1ca" in rendered
