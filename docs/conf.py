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
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]
