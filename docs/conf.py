from __future__ import annotations

from devflows.project import load_project

# Identity is sourced from the central .config/project.yaml.
_project = load_project()

project = "DevFlows"
author = "DevFlows maintainers"
copyright = "2026, DevFlows maintainers"

extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinx_design",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_title = "DevFlows"
html_baseurl = _project.docs_url
html_theme_options = {
    "github_url": _project.github_url,
    "navbar_align": "left",
    "show_toc_level": 2,
    # Pre-release banner shown on every page.
    "announcement": (
        "DevFlows is <strong>pre-release</strong>: no versions are published "
        "yet and interfaces may change. Pin an exact per-workflow tag or a "
        "commit SHA."
    ),
    # Category/section nav for the catalog, which `devflows docs` groups by
    # `docs.category` (one heading and a hidden per-category toctree each):
    # collapse extra top-level links into a "More" dropdown, and let the primary
    # sidebar expose the category-grouped catalog and per-workflow reference pages.
    "header_links_before_dropdown": 4,
    "navigation_depth": 3,
    "show_nav_level": 1,
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]
