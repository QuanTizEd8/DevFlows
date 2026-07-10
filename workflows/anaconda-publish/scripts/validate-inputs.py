"""Fail-fast input validation for anaconda-publish (validate job).

Env maps ONLY ``inputs.*`` (secret-presence checks live in the per-job tokenless
preflight). Imports the sibling modules parsing / arguments / manifest.
"""

from __future__ import annotations

import json
import os

import arguments
import manifest
import parsing


def main() -> int:
    owner = _validate_owner()
    _validate_timeout()

    upload_enabled = _bool("UPLOAD_ENABLED")
    promote_enabled = _bool("PROMOTE_ENABLED")
    maintain_enabled = _bool("MAINTAIN_ENABLED")
    dry_run = _bool("PUBLISH_DRY_RUN_ENABLED")

    if maintain_enabled and (upload_enabled or promote_enabled):
        raise SystemExit(
            "maintain-enabled is mutually exclusive with upload-enabled and "
            "promote-enabled (a call publishes or destroys, never both)."
        )
    if not (upload_enabled or promote_enabled or maintain_enabled):
        raise SystemExit(
            "Nothing to do: enable at least one of upload-enabled, "
            "promote-enabled, or maintain-enabled."
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
        return parsing.validate_owner(os.environ.get("PUBLISH_OWNER", ""))
    except parsing.SpecError as error:
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
        return parsing.validate_label(os.environ.get(env_name, ""), field=field)
    except parsing.SpecError as error:
        raise SystemExit(str(error)) from error


def _validate_upload(owner: str) -> None:
    # Distributions can only arrive through the artifact-download channel (a source
    # build would bypass digest verification and coexist with the credential).
    if not _bool("ARTIFACT_DOWNLOAD_ENABLED"):
        raise SystemExit(
            "upload-enabled is true but artifact-download-enabled is false; conda "
            "distributions can only arrive through the artifact-download channel."
        )

    _validate_dist_path()

    manifest_raw = os.environ.get("PUBLISH_DIST_MANIFEST", "").strip()
    if not manifest_raw:
        raise SystemExit(
            "publish-dist-manifest is required when upload-enabled is true; pass "
            "python-build's dist-manifest output."
        )
    try:
        manifest_data = json.loads(manifest_raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"publish-dist-manifest is not valid JSON: {error}.") from error
    if not isinstance(manifest_data, dict) or manifest_data.get("schema") != 1:
        raise SystemExit('publish-dist-manifest must be a schema-1 object ({"schema": 1, ...}).')

    try:
        conda_entries = manifest.conda_manifest_entries(manifest_data)
    except parsing.SpecError as error:
        raise SystemExit(f"publish-dist-manifest is malformed: {error}") from error
    if not conda_entries:
        raise SystemExit(
            "publish-dist-manifest contains no conda packages (no kind=conda entries)."
        )

    # Chaining-misconfig catch: the manifest's conda-channel artifact must be the
    # one this call downloads.
    download_name = os.environ.get("ARTIFACT_DOWNLOAD_NAME", "").strip()
    artifacts = manifest_data.get("artifacts")
    manifest_channel = ""
    if isinstance(artifacts, dict):
        manifest_channel = str(artifacts.get("conda-channel") or "")
    if download_name and manifest_channel and download_name != manifest_channel:
        raise SystemExit(
            f"publish-dist-manifest artifacts.conda-channel {manifest_channel!r} does "
            f"not match artifact-download-name {download_name!r}."
        )

    _validate_extra_arguments()
    _validate_existing_mode()


def _validate_dist_path() -> None:
    raw = os.environ.get("PUBLISH_DIST_PATH", "").strip()
    if not raw:
        raise SystemExit(
            "publish-dist-path is required when upload-enabled is true; set it to "
            "the artifact-download-path."
        )
    if os.path.isabs(raw) or ".." in raw.replace("\\", "/").split("/"):
        raise SystemExit(
            f"publish-dist-path must be a workspace-relative path without '..': got {raw!r}."
        )


def _validate_extra_arguments() -> None:
    try:
        arguments.parse_extra_arguments(
            os.environ.get("UPLOAD_ARGUMENTS", ""), field="upload-arguments"
        )
    except parsing.SpecError as error:
        raise SystemExit(str(error)) from error


def _validate_existing_mode() -> None:
    try:
        arguments.validate_existing_mode(os.environ.get("UPLOAD_EXISTING_MODE", ""))
    except parsing.SpecError as error:
        raise SystemExit(str(error)) from error


def _validate_promote(upload_enabled: bool, upload_label: str) -> None:
    promote_label = _validate_label("PROMOTE_LABEL", "promote-label")
    if promote_label == upload_label:
        raise SystemExit(f"upload-label and promote-label must differ (both {promote_label!r}).")
    promote_specs = os.environ.get("PROMOTE_SPECS", "")
    if not upload_enabled:
        # Standalone promote-only call: specs must be explicit.
        try:
            parsing.validate_spec_list(promote_specs, field="promote-specs")
        except parsing.SpecError as error:
            if not parsing.parse_spec_list(promote_specs):
                raise SystemExit(
                    "promote-specs is required for a promote-only call (upload-enabled is false)."
                ) from error
            raise SystemExit(str(error)) from error
    elif parsing.parse_spec_list(promote_specs):
        # Chained mode derives specs from the verified set; still validate an explicit
        # override so a smuggled owner is rejected before an irreversible run.
        try:
            parsing.validate_spec_list(promote_specs, field="promote-specs")
        except parsing.SpecError as error:
            raise SystemExit(str(error)) from error


def _validate_maintain(owner: str, dry_run: bool) -> None:
    try:
        parsing.validate_spec_list(
            os.environ.get("MAINTAIN_REMOVE_SPECS", ""), field="maintain-remove-specs"
        )
    except parsing.SpecError as error:
        raise SystemExit(str(error)) from error
    if dry_run:
        return
    confirm = os.environ.get("MAINTAIN_CONFIRM", "")
    if confirm != owner:
        raise SystemExit(
            "maintain-confirm must equal publish-owner exactly to arm a destructive "
            f"removal (type-the-name guard). Set it to {owner!r}, or use dry-run."
        )


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
