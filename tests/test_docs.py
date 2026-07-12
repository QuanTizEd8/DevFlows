import dataclasses

from devflows.catalog import load_catalog
from devflows.docs import render_catalog, render_workflow

_CATALOG = {item.id: item for item in load_catalog()}


def test_catalog_docs_include_workflow_page() -> None:
    rendered = render_catalog(load_catalog())

    assert "workflows/devcontainer-build" in rendered
    assert "workflows/pandoc" in rendered
    assert "workflows/writeback" in rendered


def test_catalog_groups_by_category_in_deliberate_order() -> None:
    rendered = render_catalog(load_catalog())

    # One `##` heading per populated category, in the curated presentation order.
    headings = [line[3:] for line in rendered.splitlines() if line.startswith("## ")]
    assert headings == [
        "Documents",
        "Pages",
        "Python",
        "Publishing",
        "Containers",
        "Utilities",
    ]


def test_catalog_entries_are_doc_crossrefs_with_summary() -> None:
    rendered = render_catalog(load_catalog())

    # Each entry is a `{doc}` cross-reference carrying the one-line summary, and
    # the workflow appears under its own category's section.
    documents = rendered.split("## Documents", 1)[1].split("## Pages", 1)[0]
    assert "- {doc}`workflows/pandoc` — Convert documents" in documents
    # Every page stays wired into the nav via a hidden per-category toctree, so
    # there are no orphan warnings and no flat maxdepth toctree remains.
    assert "```{toctree}\n:hidden:" in rendered
    assert ":maxdepth: 1" not in rendered


def test_catalog_unknown_and_uncategorized_ordering() -> None:
    catalog = load_catalog()
    by_id = {item.id: item for item in catalog}
    # An unrecognized category sorts alphabetically after the curated order;
    # a workflow with no category falls under "Other", which sorts last.
    zzz = dataclasses.replace(
        by_id["writeback"],
        metadata={**by_id["writeback"].metadata, "docs": {"category": "Zebra"}},
    )
    none = dataclasses.replace(
        by_id["pandoc"],
        metadata={key: value for key, value in by_id["pandoc"].metadata.items() if key != "docs"},
    )
    rendered = render_catalog([zzz, none])
    headings = [line[3:] for line in rendered.splitlines() if line.startswith("## ")]
    assert headings == ["Zebra", "Other"]


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


def test_permissions_section_renders_caller_union() -> None:
    # deploy-pages elevates per job (deploy: pages/id-token write; package:
    # actions/contents read). The Permissions section must render that full caller
    # union, not just the read-only workflow-level block.
    rendered = render_workflow(_CATALOG["deploy-pages"])
    permissions = rendered.split("## Permissions", 1)[1].split("## Examples", 1)[0]
    assert "Required caller permissions" in permissions
    for line in (
        "- `actions`: `read`",
        "- `contents`: `read`",
        "- `id-token`: `write`",
        "- `pages`: `write`",
    ):
        assert line in permissions


def test_docs_build_permissions_include_job_level_actions_read() -> None:
    # docs-build is contents: read at the top level but its io channels add
    # actions: read per job; the union must surface actions: read.
    rendered = render_workflow(_CATALOG["docs-build"])
    permissions = rendered.split("## Permissions", 1)[1].split("## Examples", 1)[0]
    assert "- `actions`: `read`" in permissions
    assert "- `contents`: `read`" in permissions


def test_devcontainer_build_docs_include_filtered_interface() -> None:
    devcontainer_build = {item.id: item for item in load_catalog()}["devcontainer-build"]
    rendered = render_workflow(devcontainer_build)

    assert "# Devcontainer Build" in rendered
    assert (
        "QuanTizEd8/DevFlows/.github/workflows/devcontainer-build.yaml@devcontainer-build/vX.Y.Z"
        in rendered
    )
    assert "| image-name | string | True |  |" in rendered
    assert "build-matrix" in rendered
    assert "prepare-command" in rendered
    assert "devcontainer-push" in rendered
    assert "| runCmd |" not in rendered
    assert "| registry-auth |" not in rendered
    assert "| save-always |" not in rendered


def test_workflow_docs_include_source_link() -> None:
    rendered = render_workflow(_CATALOG["pandoc"])

    assert "## Source" in rendered
    assert "https://github.com/QuanTizEd8/DevFlows/tree/main/workflows/pandoc/" in rendered


def test_active_workflow_renders_status_badge() -> None:
    rendered = render_workflow(_CATALOG["pandoc"])

    assert "**Status:** Active" in rendered
    # An active workflow must not raise a deprecation/experimental admonition.
    assert "{warning}" not in rendered
    assert "{caution}" not in rendered


def test_deprecated_and_experimental_render_distinct_admonitions() -> None:
    base = _CATALOG["pandoc"]

    deprecated = dataclasses.replace(base, metadata={**base.metadata, "status": "deprecated"})
    rendered_deprecated = render_workflow(deprecated)
    assert "```{warning}" in rendered_deprecated
    assert "Status: Deprecated" in rendered_deprecated
    assert "**Status:** Active" not in rendered_deprecated

    experimental = dataclasses.replace(base, metadata={**base.metadata, "status": "experimental"})
    rendered_experimental = render_workflow(experimental)
    assert "```{caution}" in rendered_experimental
    assert "Status: Experimental" in rendered_experimental
    assert "**Status:** Active" not in rendered_experimental

    # The two states must render visibly distinct admonition directives.
    assert "```{warning}" not in rendered_experimental
    assert "```{caution}" not in rendered_deprecated


def test_composition_hint_keyed_on_category() -> None:
    # Python workflows get the build/test/lint composition tip.
    python_build = render_workflow(_CATALOG["python-build"])
    assert "## Composition" in python_build
    assert "```{tip}" in python_build
    assert "`python-build`" in python_build.split("## Composition", 1)[1]

    # Publishing consumes python-build's dist-manifest.
    pypi = render_workflow(_CATALOG["pypi-publish"])
    assert "`dist-manifest`" in pypi.split("## Composition", 1)[1]

    # A category without a curated hint renders no Composition section.
    writeback = render_workflow(_CATALOG["writeback"])
    assert "## Composition" not in writeback
