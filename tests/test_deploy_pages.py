from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from devflows.catalog import load_catalog
from devflows.publish import build_published_workflow

# The GitHub Pages actions are pinned inline (not in the shared registry) because
# convention item 20 makes the registry the single version-of-truth for every
# internal workflow, and the repo's own devflows-docs.yaml pins older Pages action
# versions that this workflow-scoped change must not touch.
UPLOAD_PAGES_ARTIFACT = "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9"
CONFIGURE_PAGES = "actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d"
DEPLOY_PAGES = "actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128"

VALIDATE = Path("workflows/deploy-pages/scripts/validate-inputs.py")

_ENV_KEYS = (
    "PAGES_PATH",
    "PAGES_ARTIFACT_ENABLED",
    "PAGES_DEPLOY_ENABLED",
    "PAGES_ARTIFACT_NAME",
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_pages_inputs", VALIDATE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_env(monkeypatch, **values: str) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


# --------------------------------------------------------------------------- #
# validate-inputs.py behavior (incl. every failure path)
# --------------------------------------------------------------------------- #


def test_noop_call_is_rejected(monkeypatch) -> None:
    module = _load_module()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="false",
        PAGES_DEPLOY_ENABLED="false",
        PAGES_ARTIFACT_NAME="github-pages",
    )
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "Nothing to do" in str(excinfo.value)


def test_empty_artifact_name_is_rejected(monkeypatch) -> None:
    module = _load_module()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="true",
        PAGES_DEPLOY_ENABLED="false",
        PAGES_ARTIFACT_NAME="",
    )
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "pages-artifact-name must not be empty" in str(excinfo.value)


def test_missing_path_when_packaging_is_rejected(monkeypatch) -> None:
    module = _load_module()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="true",
        PAGES_DEPLOY_ENABLED="false",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_PATH="",
    )
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "pages-path is required" in str(excinfo.value)


def test_nonexistent_path_is_rejected(monkeypatch, tmp_path) -> None:
    module = _load_module()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="true",
        PAGES_DEPLOY_ENABLED="false",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_PATH="does-not-exist",
    )
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "does not exist or is not a directory" in str(excinfo.value)


def test_path_outside_workspace_is_rejected(monkeypatch, tmp_path) -> None:
    module = _load_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="true",
        PAGES_DEPLOY_ENABLED="false",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_PATH="../escape",
    )
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "GITHUB_WORKSPACE" in str(excinfo.value)


def test_empty_directory_is_rejected(monkeypatch, tmp_path) -> None:
    module = _load_module()
    (tmp_path / "site").mkdir()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="true",
        PAGES_DEPLOY_ENABLED="false",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_PATH="site",
    )
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "must contain at least one file" in str(excinfo.value)


def test_valid_site_directory_passes(monkeypatch, tmp_path) -> None:
    module = _load_module()
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>site</h1>", encoding="utf-8")
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="true",
        PAGES_DEPLOY_ENABLED="true",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_PATH="site",
    )
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    assert module.main() == 0


def test_nested_file_satisfies_non_empty_check(monkeypatch, tmp_path) -> None:
    module = _load_module()
    nested = tmp_path / "site" / "assets"
    nested.mkdir(parents=True)
    (nested / "app.js").write_text("console.log(1)", encoding="utf-8")
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="true",
        PAGES_DEPLOY_ENABLED="false",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_PATH="site",
    )
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    assert module.main() == 0


def test_path_set_when_packaging_disabled_is_rejected(monkeypatch) -> None:
    module = _load_module()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="false",
        PAGES_DEPLOY_ENABLED="true",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_PATH="site",
    )
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "must be empty when pages-artifact-enabled is false" in str(excinfo.value)


def test_deploy_only_mode_passes(monkeypatch) -> None:
    module = _load_module()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="false",
        PAGES_DEPLOY_ENABLED="true",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_PATH="",
    )
    assert module.main() == 0


def test_deploy_timeout_ms_is_emitted(monkeypatch, tmp_path) -> None:
    module = _load_module()
    output = tmp_path / "gh_output"
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="false",
        PAGES_DEPLOY_ENABLED="true",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_TIMEOUT_MINUTES="10",
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert module.main() == 0
    # Minutes -> milliseconds; 10 minutes matches deploy-pages' upstream default.
    assert "deploy-timeout-ms=600000\n" in output.read_text(encoding="utf-8")


def test_non_numeric_timeout_is_rejected(monkeypatch, tmp_path) -> None:
    module = _load_module()
    _set_env(
        monkeypatch,
        PAGES_ARTIFACT_ENABLED="false",
        PAGES_DEPLOY_ENABLED="true",
        PAGES_ARTIFACT_NAME="github-pages",
        PAGES_TIMEOUT_MINUTES="soon",
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "must be a number" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Generated interface snapshot (design contract after conventions)
# --------------------------------------------------------------------------- #


def _published() -> dict[str, Any]:
    for item in load_catalog():
        if item.id == "deploy-pages":
            return build_published_workflow(item)
    raise AssertionError("deploy-pages workflow not found in catalog")


def _workflow_call(published: dict[str, Any]) -> dict[str, Any]:
    return published["on"]["workflow_call"]


def test_workflow_specific_inputs_match_conventions() -> None:
    inputs = _workflow_call(_published())["inputs"]
    expected = {
        "pages-path",
        "pages-artifact-enabled",
        "pages-deploy-enabled",
        "pages-artifact-name",
        "pages-artifact-retention-days",
        "pages-artifact-include-hidden-files",
        "pages-environment-name",
        "pages-timeout-minutes",
    }
    assert expected <= set(inputs)
    # The upload toggle was renamed to align with docs-build (convention #14).
    assert "pages-upload-enabled" not in inputs
    # Channel inputs are generator-injected, never hand-authored.
    assert "checkout-enabled" in inputs
    assert "artifact-download-enabled" in inputs
    assert "artifact-upload-enabled" not in inputs


def test_outputs_use_pages_prefix() -> None:
    outputs = _workflow_call(_published())["outputs"]
    assert set(outputs) == {"pages-url", "pages-artifact-id"}
    # page-url was renamed to pages-url (convention #13); upstream page_url mapping.
    assert "page-url" not in outputs
    assert outputs["pages-url"]["value"] == "${{ jobs.deploy.outputs.pages-url }}"
    assert outputs["pages-artifact-id"]["value"] == "${{ jobs.package.outputs.pages-artifact-id }}"


def test_package_job_is_least_privilege_read_only() -> None:
    package = _published()["jobs"]["package"]
    assert package["permissions"] == {"contents": "read", "actions": "read"}
    assert package["outputs"] == {
        "pages-artifact-id": "${{ steps.upload.outputs.artifact_id }}",
        "deploy-timeout-ms": "${{ steps.validate.outputs.deploy-timeout-ms }}",
    }
    # Generator injects checkout + artifact-download + materialize before the
    # domain steps; validation runs before packaging.
    step_names = [step.get("name") for step in package["steps"]]
    assert step_names.index("Validate inputs") < step_names.index("Upload Pages artifact")
    assert "Checkout repository" in step_names
    assert "Download artifacts" in step_names


def test_deploy_job_holds_only_pages_and_id_token_write() -> None:
    deploy = _published()["jobs"]["deploy"]
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert deploy["needs"] == "package"
    assert deploy["if"] == "inputs.pages-deploy-enabled"
    assert deploy["concurrency"] == {
        "group": "deploy-pages-${{ inputs.pages-environment-name }}",
        "cancel-in-progress": False,
    }
    assert deploy["environment"]["name"] == "${{ inputs.pages-environment-name }}"
    assert deploy["environment"]["url"] == "${{ steps.deploy.outputs.page_url }}"
    assert deploy["outputs"] == {"pages-url": "${{ steps.deploy.outputs.page_url }}"}
    # The elevated Pages token job never checks out code or runs a script; the
    # minutes->ms timeout is computed by the package job and consumed here.
    step_names = [step.get("name") for step in deploy["steps"]]
    assert "Checkout repository" not in step_names
    assert all("run" not in step for step in deploy["steps"])
    deploy_step = next(s for s in deploy["steps"] if s.get("id") == "deploy")
    assert deploy_step["with"]["timeout"] == "${{ needs.package.outputs.deploy-timeout-ms }}"
    assert deploy_step["with"]["artifact_name"] == "${{ inputs.pages-artifact-name }}"


def test_pages_actions_are_sha_pinned_inline() -> None:
    published = _published()
    uses = {
        step["uses"]
        for job in published["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and "uses" in step
    }
    assert UPLOAD_PAGES_ARTIFACT in uses
    assert CONFIGURE_PAGES in uses
    assert DEPLOY_PAGES in uses
