from devflows.catalog import load_catalog
from devflows.docs import render_catalog, render_workflow


def test_catalog_docs_include_workflow_page() -> None:
    rendered = render_catalog(load_catalog())

    assert "workflows/build-devcontainer" in rendered
    assert "workflows/pandoc" in rendered
    assert "workflows/writeback" in rendered


def test_workflow_docs_include_interface_sections() -> None:
    pandoc = {item.id: item for item in load_catalog()}["pandoc"]
    rendered = render_workflow(pandoc)

    assert "# Pandoc" in rendered
    assert "| pandoc-image | string | False | pandoc/latex:3-ubuntu |" in rendered
    # Pre-1.0 (0.x): the reference recommends exact tags / SHAs, not a moving
    # major tag, and documents that moving majors begin at 1.0.
    assert "QuanTizEd8/DevFlows/.github/workflows/pandoc.yaml@pandoc/vX.Y.Z" in rendered
    assert "pre-1.0 (0.x)" in rendered
    assert "Moving major tags (`pandoc/vN`) begin at the 1.0 release." in rendered


def test_pandoc_docs_include_image_notes() -> None:
    pandoc = {item.id: item for item in load_catalog()}["pandoc"]
    rendered = render_workflow(pandoc)

    assert "# Pandoc" in rendered
    assert "pandoc/latex:3-ubuntu" in rendered
    assert "pandoc-image: pandoc/core:3.8" in rendered
    assert "artifact-upload-enabled: true" in rendered
    assert "artifact-download-enabled" in rendered
    assert "commit-enabled" in rendered
    assert "`/.pandoc/templates/eisvogel.latex`" in rendered
    assert "pandoc/extra image may need explicit template paths" in rendered
    assert "`markdown-html-artifact`" in rendered
    assert "`working-directory-local`" in rendered


def test_build_devcontainer_docs_include_filtered_interface() -> None:
    build_devcontainer = {item.id: item for item in load_catalog()}["build-devcontainer"]
    rendered = render_workflow(build_devcontainer)

    assert "# Build Devcontainer" in rendered
    assert (
        "QuanTizEd8/DevFlows/.github/workflows/build-devcontainer.yaml@build-devcontainer/vX.Y.Z"
        in rendered
    )
    assert "| image-name | string | True |  |" in rendered
    assert "build-matrix" in rendered
    assert "prepare-command" in rendered
    assert "devcontainer-push" in rendered
    assert "| runCmd |" not in rendered
    assert "| registry-auth |" not in rendered
    assert "| save-always |" not in rendered
