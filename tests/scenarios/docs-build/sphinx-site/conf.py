# Minimal Sphinx configuration for DevFlows docs-build scenarios.
# Deliberately dependency-free (bundled alabaster theme, no extensions) so the
# fixture builds identically in a container, uv, pip, pixi, or micromamba env.
project = "DevFlows Docs Build Fixture"
author = "DevFlows maintainers"
version = "0.0.0"
release = "0.0.0"

extensions = []
templates_path = []
exclude_patterns = ["_build"]

html_theme = "alabaster"
html_static_path = []
