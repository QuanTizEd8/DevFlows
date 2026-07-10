from __future__ import annotations

import json
import os
import shlex
from pathlib import PurePosixPath

# The only two indexes OIDC trusted publishing works against. pypi-publish is
# trusted-publishing-only, so an arbitrary repository URL could only ever be a
# misconfiguration; it is rejected rather than silently implying a token flow.
VALID_INDICES = {"pypi", "testpypi"}
_REPOSITORY_URLS = {
    "pypi": "https://upload.pypi.org/legacy/",
    "testpypi": "https://test.pypi.org/legacy/",
}
# Distributions to publish. A manifest carrying only conda-kind files is a
# nothing-to-publish call for this workflow (anaconda-publish handles those).
PUBLISHABLE_KINDS = {"sdist", "wheel"}
# Flags in install-check-arguments that would select a package index and defeat
# the typed publish-index target (the index is chosen by publish-index alone).
_INDEX_SELECTION_FLAGS = {"-i", "--index-url", "--extra-index-url"}


def main() -> int:
    """Fail loudly on any pypi-publish misconfiguration before ingestion or upload.

    The step running this script maps only ``inputs.*`` expressions into the
    environment, so the expect: validation-failure harness can reconstruct the
    same env and exercise every rejection below directly, without a reusable call.
    Checks are ordered cheapest-first and never touch the filesystem: a
    validation-failure scenario reaches a specific rejection by supplying valid
    values for every input checked before it.
    """
    index = _validate_index()
    _validate_manifest()
    _validate_dist_path()
    _validate_environment_name()
    _validate_ingestion()
    _validate_dry_run_and_install_check()
    _validate_install_check_arguments()
    _emit_repository_url(index)
    return 0


def _validate_index() -> str:
    index = os.environ.get("PUBLISH_INDEX", "").strip()
    if index not in VALID_INDICES:
        raise SystemExit(
            f"publish-index must be 'pypi' or 'testpypi' (got {index!r}). Arbitrary "
            "repository URLs are rejected: pypi-publish uploads only via OIDC trusted "
            "publishing, which PyPI and TestPyPI alone support. To stage a release, "
            "call once with 'testpypi' and then with 'pypi'."
        )
    return index


def _validate_manifest() -> None:
    raw = os.environ.get("PUBLISH_DIST_MANIFEST", "").strip()
    if not raw:
        raise SystemExit(
            "publish-dist-manifest is required: chain python-build's dist-manifest "
            "output (schema 1) so only digest-verified sdist and wheel files are uploaded."
        )
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"publish-dist-manifest is not valid JSON: {error}.") from None
    if not isinstance(manifest, dict):
        raise SystemExit("publish-dist-manifest must be a JSON object.")
    schema = manifest.get("schema")
    if schema != 1:
        raise SystemExit(
            f"unsupported dist-manifest schema {schema!r}; pypi-publish understands schema 1."
        )
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SystemExit("publish-dist-manifest 'files' must be a list.")
    publishable = [
        entry
        for entry in files
        if isinstance(entry, dict) and entry.get("kind") in PUBLISHABLE_KINDS
    ]
    if not publishable:
        raise SystemExit(
            "publish-dist-manifest contains no sdist or wheel distributions to publish "
            "(pypi-publish uploads only sdist and wheel kinds)."
        )


def _validate_dist_path() -> None:
    raw = os.environ.get("PUBLISH_DIST_PATH", "").strip()
    if not raw:
        raise SystemExit(
            "publish-dist-path is required: it names the downloaded distribution "
            "directory to verify and publish (typically equal to artifact-download-path)."
        )
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(
            f"publish-dist-path must be a workspace-relative path without '..': {raw!r}."
        )


def _validate_environment_name() -> None:
    if not os.environ.get("PUBLISH_ENVIRONMENT_NAME", "").strip():
        raise SystemExit(
            "publish-environment-name must not be empty: the publish job binds to this "
            "GitHub environment, where release protection rules and required reviewers live."
        )


def _validate_ingestion() -> None:
    if not _truthy(os.environ.get("ARTIFACT_DOWNLOAD_ENABLED", "")):
        raise SystemExit(
            "pypi-publish has no checkout; distributions can only arrive through the "
            "artifact-download channel, so artifact-download-enabled must be true."
        )


def _validate_dry_run_and_install_check() -> None:
    dry_run = _truthy(os.environ.get("PUBLISH_DRY_RUN_ENABLED", ""))
    install_check = _truthy(os.environ.get("INSTALL_CHECK_ENABLED", ""))
    if dry_run and install_check:
        raise SystemExit(
            "install-check-enabled requires a real publish, but publish-dry-run-enabled "
            "is true; the dry run skips the publish job, so there is nothing to install."
        )


def _validate_install_check_arguments() -> None:
    raw = os.environ.get("INSTALL_CHECK_ARGUMENTS", "")
    try:
        tokens = shlex.split(raw)
    except ValueError as error:
        raise SystemExit(f"install-check-arguments is not valid shell syntax: {error}.") from None
    for token in tokens:
        if _is_index_selection_flag(token):
            raise SystemExit(
                "install-check-arguments must not select a package index "
                "(-i/--index-url/--extra-index-url); the index is chosen by publish-index "
                f"and the target version is exact-pinned. Offending argument: {token!r}."
            )


def _is_index_selection_flag(token: str) -> bool:
    name = token.split("=", 1)[0]
    if name in _INDEX_SELECTION_FLAGS:
        return True
    # Short form with an attached value, e.g. -ihttps://example/simple.
    return token.startswith("-i") and not token.startswith("--")


def _emit_repository_url(index: str) -> None:
    """Expose the upload endpoint the publish job passes to gh-action-pypi-publish.

    Derived here (never caller-supplied) and consumed as needs.validate.outputs so
    the credentialed publish job stays free of index-selection logic. No-op off CI
    (GITHUB_OUTPUT unset), so unit tests of the rejection paths do not require it.
    """
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"repository-url={_REPOSITORY_URLS[index]}\n")


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
