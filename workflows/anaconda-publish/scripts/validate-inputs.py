"""Fail-fast input validation for anaconda-publish.

Runs in the ``validate`` job with an env block that maps ONLY ``inputs.*``
expressions (the validation-failure harness reconstructs that env directly), so
secret-presence checks live in the per-job tokenless preflight instead. This
script imports the sibling ``specs.py`` (materialized alongside it); the
validate step's run body carries a ``${DEVFLOWS_SCRIPT_ROOT}/anaconda-publish/
specs.py`` comment so the sync step inlines it.
"""

from __future__ import annotations

import json
import os

import specs


def main() -> int:
    owner = _validate_owner()
    _validate_timeout()

    upload_enabled = _bool("UPLOAD_ENABLED")
    promote_enabled = _bool("PROMOTE_ENABLED")
    maintain_enabled = _bool("MAINTAIN_ENABLED")
    dry_run = _bool("PUBLISH_DRY_RUN_ENABLED")

    # A call either publishes (upload/promote) or destroys (maintain), never both.
    if maintain_enabled and (upload_enabled or promote_enabled):
        raise SystemExit(
            "maintain-enabled is mutually exclusive with upload-enabled and "
            "promote-enabled; a call either publishes or destroys, never both."
        )
    if not (upload_enabled or promote_enabled or maintain_enabled):
        raise SystemExit(
            "Nothing to do: enable at least one of upload-enabled, promote-enabled, "
            "or maintain-enabled. This workflow never silently no-ops."
        )

    upload_label = _validate_label("UPLOAD_LABEL", "upload-label")

    if upload_enabled:
        _validate_upload(owner)

    if promote_enabled:
        _validate_promote(upload_enabled, upload_label)

    if maintain_enabled:
        _validate_maintain(owner, dry_run)

    return 0


def _validate_owner() -> str:
    try:
        return specs.validate_owner(os.environ.get("PUBLISH_OWNER", ""))
    except specs.SpecError as error:
        raise SystemExit(str(error)) from error


def _validate_timeout() -> None:
    raw = os.environ.get("PUBLISH_TIMEOUT_MINUTES", "").strip()
    if not raw:
        return
    try:
        value = int(raw)
    except ValueError as error:
        raise SystemExit(f"publish-timeout-minutes must be an integer; got {raw!r}.") from error
    if value <= 0:
        raise SystemExit(f"publish-timeout-minutes must be a positive integer; got {value}.")


def _validate_label(env_name: str, field: str) -> str:
    try:
        return specs.validate_label(os.environ.get(env_name, ""), field=field)
    except specs.SpecError as error:
        raise SystemExit(str(error)) from error


def _validate_upload(owner: str) -> None:
    # Distributions can only arrive through the artifact-download channel; a build
    # from source would bypass digest verification and coexist with the credential.
    if not _bool("ARTIFACT_DOWNLOAD_ENABLED"):
        raise SystemExit(
            "upload-enabled is true but artifact-download-enabled is false; conda "
            "distributions can only arrive through the artifact-download channel. "
            "Set artifact-download-enabled: true and artifact-download-name to the "
            "python-build conda-artifact-name output."
        )

    _validate_dist_path()

    manifest_raw = os.environ.get("PUBLISH_DIST_MANIFEST", "").strip()
    if not manifest_raw:
        raise SystemExit(
            "publish-dist-manifest is required when upload-enabled is true; "
            "publishing without a digest manifest is refused by design. Pass "
            "python-build's dist-manifest output."
        )
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"publish-dist-manifest is not valid JSON: {error}.") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise SystemExit('publish-dist-manifest must be a schema-1 object ({"schema": 1, ...}).')

    try:
        conda_entries = specs.conda_manifest_entries(manifest)
    except specs.SpecError as error:
        raise SystemExit(f"publish-dist-manifest is malformed: {error}") from error
    if not conda_entries:
        raise SystemExit(
            "publish-dist-manifest contains no conda packages (no kind=conda file "
            "entries); nothing to upload to anaconda.org."
        )

    # Loud chaining-misconfig catch: the manifest's declared conda-channel artifact
    # must be the one this call downloads.
    download_name = os.environ.get("ARTIFACT_DOWNLOAD_NAME", "").strip()
    artifacts = manifest.get("artifacts")
    manifest_channel = ""
    if isinstance(artifacts, dict):
        manifest_channel = str(artifacts.get("conda-channel") or "")
    if download_name and manifest_channel and download_name != manifest_channel:
        raise SystemExit(
            f"publish-dist-manifest artifacts.conda-channel {manifest_channel!r} "
            f"does not match artifact-download-name {download_name!r}; the manifest "
            "and the downloaded artifact are from different builds."
        )

    _validate_extra_arguments()
    _validate_existing_mode()


def _validate_dist_path() -> None:
    raw = os.environ.get("PUBLISH_DIST_PATH", "").strip()
    if not raw:
        raise SystemExit(
            "publish-dist-path is required when upload-enabled is true; set it to "
            "the artifact-download-path the conda channel is downloaded into."
        )
    if os.path.isabs(raw) or ".." in raw.replace("\\", "/").split("/"):
        raise SystemExit(
            f"publish-dist-path must be a workspace-relative path without '..': got {raw!r}."
        )


def _validate_extra_arguments() -> None:
    try:
        specs.parse_extra_arguments(
            os.environ.get("UPLOAD_ARGUMENTS", ""), field="upload-arguments"
        )
    except specs.SpecError as error:
        raise SystemExit(str(error)) from error


def _validate_existing_mode() -> None:
    try:
        specs.validate_existing_mode(os.environ.get("UPLOAD_EXISTING_MODE", ""))
    except specs.SpecError as error:
        raise SystemExit(str(error)) from error


def _validate_promote(upload_enabled: bool, upload_label: str) -> None:
    promote_label = _validate_label("PROMOTE_LABEL", "promote-label")
    if promote_label == upload_label:
        raise SystemExit(
            f"upload-label and promote-label must differ (both {promote_label!r}); "
            "promotion relabels packages from the staging label to the final label."
        )
    promote_specs = os.environ.get("PROMOTE_SPECS", "")
    if not upload_enabled:
        # Standalone promote-only call: specs must be explicit.
        try:
            specs.validate_spec_list(promote_specs, field="promote-specs")
        except specs.SpecError as error:
            if not specs.parse_spec_list(promote_specs):
                raise SystemExit(
                    "promote-specs is required for a promote-only call "
                    "(upload-enabled is false); list the package/version specs to "
                    "relabel, typically from a previous run's staged-specs output."
                ) from error
            raise SystemExit(str(error)) from error
    elif specs.parse_spec_list(promote_specs):
        # Chained mode derives specs from the verified upload set; still validate any
        # explicit override so a smuggled owner is rejected before an irreversible run.
        try:
            specs.validate_spec_list(promote_specs, field="promote-specs")
        except specs.SpecError as error:
            raise SystemExit(str(error)) from error


def _validate_maintain(owner: str, dry_run: bool) -> None:
    try:
        specs.validate_spec_list(
            os.environ.get("MAINTAIN_REMOVE_SPECS", ""), field="maintain-remove-specs"
        )
    except specs.SpecError as error:
        raise SystemExit(str(error)) from error
    if dry_run:
        return
    confirm = os.environ.get("MAINTAIN_CONFIRM", "")
    if confirm != owner:
        raise SystemExit(
            "maintain-confirm must equal publish-owner exactly to arm a destructive "
            "removal (the type-the-name-to-destroy guard). Set maintain-confirm to "
            f"{owner!r}, or run with publish-dry-run-enabled to rehearse."
        )


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
