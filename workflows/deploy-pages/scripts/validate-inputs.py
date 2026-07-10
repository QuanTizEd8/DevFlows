from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    """Fail loudly on any deploy-pages misconfiguration before packaging or deploying.

    The two modes are mutually exclusive on pages-path: primary mode packages a
    site DIRECTORY (pages-artifact-enabled true, pages-path set) and secondary mode
    deploys an already-Pages-format artifact by name (pages-artifact-enabled false,
    pages-path empty). A call that neither packages nor deploys is a no-op and is
    rejected rather than silently doing nothing (D14).
    """
    pages_path = os.environ.get("PAGES_PATH", "").strip()
    artifact_enabled = _truthy(os.environ.get("PAGES_ARTIFACT_ENABLED", ""))
    deploy_enabled = _truthy(os.environ.get("PAGES_DEPLOY_ENABLED", ""))
    artifact_name = os.environ.get("PAGES_ARTIFACT_NAME", "").strip()

    if not artifact_enabled and not deploy_enabled:
        raise SystemExit(
            "Nothing to do: pages-artifact-enabled and pages-deploy-enabled are both "
            "false. Enable packaging, deployment, or both."
        )

    # The name selects the artifact for both upload-pages-artifact and deploy-pages;
    # an empty name would silently break the package/deploy handoff.
    if not artifact_name:
        raise SystemExit("pages-artifact-name must not be empty.")

    if artifact_enabled:
        _validate_site_directory(pages_path)
    elif pages_path:
        raise SystemExit(
            "pages-path must be empty when pages-artifact-enabled is false. In "
            "deploy-only mode the Pages artifact named by pages-artifact-name is "
            "deployed as-is; there is no directory to package."
        )

    _emit_deploy_timeout_ms()
    return 0


def _emit_deploy_timeout_ms() -> None:
    """Expose pages-timeout-minutes to the deploy job as milliseconds.

    GitHub Actions expressions have no arithmetic operator, so the minutes->ms
    conversion deploy-pages' timeout input needs cannot live in the workflow YAML.
    The package job (which already runs this script) computes it and exposes it as
    an output the deploy job consumes, keeping the elevated pages:write/id-token:write
    deploy job free of any script. No-op off CI (GITHUB_OUTPUT unset), so unit tests
    of the validation paths do not require it.
    """
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    raw = os.environ.get("PAGES_TIMEOUT_MINUTES", "").strip()
    try:
        minutes = float(raw)
    except ValueError:
        raise SystemExit(f"pages-timeout-minutes must be a number: {raw!r}") from None
    if minutes <= 0:
        raise SystemExit(f"pages-timeout-minutes must be greater than zero: {raw!r}")
    milliseconds = int(minutes * 60000)
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"deploy-timeout-ms={milliseconds}\n")


def _validate_site_directory(pages_path: str) -> None:
    """Validate pages-path is a non-empty directory inside the workspace."""
    if not pages_path:
        raise SystemExit(
            "pages-path is required when pages-artifact-enabled is true: it names the "
            "directory packaged into the GitHub Pages artifact."
        )
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    site = (workspace / pages_path).resolve()
    if workspace != site and workspace not in site.parents:
        raise SystemExit(f"pages-path must stay inside GITHUB_WORKSPACE: {pages_path}")
    if not site.is_dir():
        raise SystemExit(f"pages-path does not exist or is not a directory: {pages_path}")
    if not any(entry.is_file() for entry in site.rglob("*")):
        raise SystemExit(f"pages-path must contain at least one file: {pages_path}")


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
