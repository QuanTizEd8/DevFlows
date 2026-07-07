from devflows.catalog import load_catalog
from devflows.docs import render_catalog, render_workflow


def test_catalog_docs_include_workflow_page() -> None:
    rendered = render_catalog(load_catalog())

    assert "workflows/hello-world" in rendered


def test_workflow_docs_include_interface_sections() -> None:
    rendered = render_workflow(load_catalog()[0])

    assert "# Hello World" in rendered
    assert "| message | string | False | Hello from DevFlows |" in rendered
    assert "owner/devflows/.github/workflows/hello-world.yaml@hello-world/v1" in rendered
