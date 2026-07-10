from __future__ import annotations

from pathlib import Path

import pytest

from devflows.errors import DevflowsError
from devflows.project import find_root, load_project


def test_find_root_walks_up_to_config(make_catalog, monkeypatch) -> None:
    root = make_catalog()
    nested = root / "workflows" / "demo" / "scripts"
    monkeypatch.chdir(nested)

    assert find_root() == root


def test_find_root_honors_explicit_override(make_catalog) -> None:
    root = make_catalog()

    assert find_root(root) == root.resolve()


def test_find_root_raises_outside_catalog(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(DevflowsError):
        find_root()


def test_find_root_rejects_bad_override(tmp_path) -> None:
    with pytest.raises(DevflowsError):
        find_root(tmp_path)


def test_load_project_exposes_identity(make_catalog) -> None:
    root = make_catalog()
    project = load_project(root)

    assert project.slug == "Example/Demo"
    assert project.github_url == "https://github.com/Example/Demo"
    assert (
        project.uses_reference("demo", "demo/v1")
        == "Example/Demo/.github/workflows/demo.yaml@demo/v1"
    )


def test_live_catalog_uses_real_identity() -> None:
    # The committed .config/project.yaml is the canonical repository identity.
    project = load_project(Path.cwd())

    assert project.slug == "QuanTizEd8/DevFlows"
    assert project.default_branch == "main"
