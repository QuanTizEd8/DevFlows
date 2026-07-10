"""Fail-fast input validation for zenodo-release (validate job).

Env maps ONLY inputs.* (secret-presence checks live in the per-job tokenless
preflight), so the validation-failure harness can reconstruct this step's env from
the scenario inputs. Checks are ordered cheapest-first and every credentialed side
effect is refused here before any environment is bound. Imports the light sibling
modules manifest and metadata.
"""

from __future__ import annotations

import json
import os
import re

import metadata

_REF_FORBIDDEN = re.compile(r"[\x00-\x20~^:?*\[\\]")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")
_CATEGORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")

_EXISTING_MODES = ("fail", "update", "skip")
_IF_NO_FILES_FOUND = ("error", "warn", "ignore")
_FILE_MODES = ("replace", "keep")
_UPLOAD_TYPES = (
    "software",
    "publication",
    "dataset",
    "poster",
    "presentation",
    "image",
    "video",
    "lesson",
    "physicalobject",
    "other",
)


def main() -> int:
    release_enabled = _bool("RELEASE_ENABLED")
    zenodo_enabled = _bool("ZENODO_ENABLED")
    if not (release_enabled or zenodo_enabled):
        raise SystemExit("Nothing to do: enable at least one of release-enabled or zenodo-enabled.")

    _validate_timeout()
    tag = _validate_tag()
    _validate_notes_exclusivity()

    if release_enabled:
        _validate_release()
    if zenodo_enabled:
        _validate_zenodo(tag)
    return 0


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


def _validate_tag() -> str:
    tag = os.environ.get("RELEASE_TAG", "").strip()
    if not tag:
        raise SystemExit("release-tag is required and must be non-empty.")
    if tag.startswith("-") or ".." in tag or tag.endswith(".lock") or _REF_FORBIDDEN.search(tag):
        raise SystemExit(
            f"release-tag must be a valid git ref (no spaces, '..', leading '-', or "
            f"control/glob characters); got {tag!r}."
        )
    return tag


def _validate_notes_exclusivity() -> None:
    notes = os.environ.get("RELEASE_NOTES", "").strip()
    notes_file = os.environ.get("RELEASE_NOTES_FILE", "").strip()
    if notes and notes_file:
        raise SystemExit(
            "release-notes and release-notes-file are mutually exclusive; set at most one."
        )


def _validate_release() -> None:
    _enum("RELEASE_EXISTING_MODE", _EXISTING_MODES, "release-existing-mode")
    _enum(
        "RELEASE_ASSET_IF_NO_FILES_FOUND",
        _IF_NO_FILES_FOUND,
        "release-asset-if-no-files-found",
    )
    _contained_path("RELEASE_NOTES_FILE", "release-notes-file")
    _contained_path("RELEASE_ASSET_SOURCE_PATH", "release-asset-source-path")
    _charset("RELEASE_ENVIRONMENT_NAME", _NAME_RE, "release-environment-name")

    category = os.environ.get("RELEASE_DISCUSSION_CATEGORY", "").strip()
    if category:
        _charset("RELEASE_DISCUSSION_CATEGORY", _CATEGORY_RE, "release-discussion-category")
        if _bool("RELEASE_DRAFT_ENABLED"):
            raise SystemExit(
                "release-discussion-category cannot be combined with release-draft-enabled "
                "(GitHub cannot link a discussion to a draft release)."
            )
    _require_download_for_globs("RELEASE_ASSET_GLOBS", "release-asset-globs")


def _validate_zenodo(tag: str) -> None:
    if not os.environ.get("ZENODO_ENVIRONMENT_NAME", "").strip():
        raise SystemExit(
            "zenodo-environment-name is required when zenodo-enabled (bind the token "
            "secret and protection rules to a GitHub environment)."
        )
    _charset("ZENODO_ENVIRONMENT_NAME", _NAME_RE, "zenodo-environment-name")
    _enum("ZENODO_UPLOAD_TYPE", _UPLOAD_TYPES, "zenodo-upload-type")
    _enum("ZENODO_NEW_VERSION_FILE_MODE", _FILE_MODES, "zenodo-new-version-file-mode")
    _enum(
        "ZENODO_ASSET_IF_NO_FILES_FOUND",
        _IF_NO_FILES_FOUND,
        "zenodo-asset-if-no-files-found",
    )
    _contained_path("ZENODO_ASSET_SOURCE_PATH", "zenodo-asset-source-path")
    _contained_path("ZENODO_METADATA_CFF_PATH", "zenodo-metadata-cff-path")

    if not os.environ.get("ZENODO_ASSET_GLOBS", "").strip():
        raise SystemExit(
            "zenodo-asset-globs is required when zenodo-enabled (a deposition with no "
            "files is nothing to upload)."
        )
    _require_download_for_globs("ZENODO_ASSET_GLOBS", "zenodo-asset-globs")

    try:
        metadata.validate_metadata_extra(os.environ.get("ZENODO_METADATA_EXTRA", ""))
    except metadata.MetadataError as error:
        raise SystemExit(str(error)) from error

    if not os.environ.get("ZENODO_METADATA_CFF_PATH", "").strip():
        try:
            metadata.require_metadata_complete(
                title=os.environ.get("ZENODO_TITLE", ""),
                creators=os.environ.get("ZENODO_CREATORS", ""),
                description=os.environ.get("ZENODO_DESCRIPTION", ""),
            )
        except metadata.MetadataError as error:
            raise SystemExit(str(error)) from error

    _validate_manifest_shape(os.environ.get("PUBLISH_DIST_MANIFEST", ""))
    _validate_publish_confirm(tag)


def _validate_manifest_shape(raw: str) -> None:
    # Cheap shape gate only; prepare and reverify do the full entry + digest check.
    raw = raw.strip()
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"publish-dist-manifest is not valid JSON: {error}.") from error
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise SystemExit('publish-dist-manifest must be a schema-1 object ({"schema": 1, ...}).')
    if not isinstance(data.get("files"), list) or not data["files"]:
        raise SystemExit("publish-dist-manifest 'files' must be a non-empty list.")


def _validate_publish_confirm(tag: str) -> None:
    if not _bool("ZENODO_PUBLISH_ENABLED"):
        return
    if _bool("ZENODO_SANDBOX_ENABLED") or _bool("PUBLISH_DRY_RUN_ENABLED"):
        return
    confirm = os.environ.get("ZENODO_PUBLISH_CONFIRM", "")
    if confirm != tag:
        raise SystemExit(
            "zenodo-publish-confirm must equal release-tag exactly to arm an "
            "irreversible real-Zenodo publish (type-the-name guard). Set it to "
            f"{tag!r}, or use zenodo-sandbox-enabled / a draft / dry-run."
        )


def _require_download_for_globs(env_name: str, field: str) -> None:
    if os.environ.get(env_name, "").strip() and not _bool("ARTIFACT_DOWNLOAD_ENABLED"):
        raise SystemExit(
            f"{field} is set but artifact-download-enabled is false; assets can only "
            "arrive through the artifact-download channel."
        )


def _enum(env_name: str, allowed: tuple[str, ...], field: str) -> None:
    value = os.environ.get(env_name, "").strip()
    if value not in allowed:
        raise SystemExit(f"{field} must be one of {', '.join(allowed)}; got {value!r}.")


def _contained_path(env_name: str, field: str) -> None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return
    if os.path.isabs(raw) or ".." in raw.replace("\\", "/").split("/"):
        raise SystemExit(f"{field} must be a workspace-relative path without '..': got {raw!r}.")


def _charset(env_name: str, pattern: re.Pattern[str], field: str) -> None:
    value = os.environ.get(env_name, "").strip()
    if value and not pattern.match(value):
        raise SystemExit(f"{field} contains unsupported characters: got {value!r}.")


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
