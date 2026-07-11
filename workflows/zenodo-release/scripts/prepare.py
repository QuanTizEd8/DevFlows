"""Credential-free resolution and dry-run preview for zenodo-release (prepare job).

Hosts the checkout channel (CITATION.cff, release-notes-file) and the
artifact-download channel (staged assets). Resolves the version, release title and
body, asset globs, and the Zenodo deposition metadata, digest-verifies assets when
a publish-dist-manifest is supplied, and emits every plan output. Runs fully in PR
CI with zero credentials; in dry-run it is the terminal job. Installs PyYAML
ephemerally (uv) for CITATION.cff parsing.
"""

from __future__ import annotations

import json
import os
import secrets as _secrets
from pathlib import Path

import assets
import cff
import dist_manifest
import hashing
import metadata


def main() -> int:
    release_enabled = _bool("RELEASE_ENABLED")
    zenodo_enabled = _bool("ZENODO_ENABLED")
    tag = os.environ.get("RELEASE_TAG", "").strip()
    version = os.environ.get("ZENODO_VERSION", "").strip() or _strip_v(tag)

    outputs = {
        "package-version": version,
        "release-tag": tag,
        "release-title": "",
        "release-body": "",
        "deposition-metadata": "",
        "release-asset-list": "",
        "zenodo-asset-list": "",
    }
    summary = ["## zenodo-release plan", "", f"Resolved version: `{version}`", ""]

    if release_enabled:
        title, body, rel_assets = _resolve_release(tag)
        outputs["release-title"] = title
        outputs["release-body"] = body
        outputs["release-asset-list"] = "\n".join(rel_assets)
        summary += [f"GitHub release title: `{title}`", ""]
        summary += _asset_summary("Release assets", rel_assets)

    if zenodo_enabled:
        meta, zen_assets = _resolve_zenodo(version)
        outputs["deposition-metadata"] = json.dumps(meta, sort_keys=True)
        outputs["zenodo-asset-list"] = "\n".join(zen_assets)
        summary += [
            f"Zenodo deposition title: `{meta['title']}`",
            f"Zenodo upload_type: `{meta['upload_type']}`",
            f"Zenodo creators: {len(meta['creators'])}",
            "",
        ]
        summary += _asset_summary("Zenodo assets", zen_assets)

    _emit_outputs(outputs)
    _write_summary(summary)
    return 0


def _resolve_release(tag: str) -> tuple[str, str, list[str]]:
    title = os.environ.get("RELEASE_NAME", "").strip() or tag
    body = _resolve_body()
    source = _source_dir("RELEASE_ASSET_SOURCE_PATH", "release-asset-source-path")
    globs = assets.parse_lines(os.environ.get("RELEASE_ASSET_GLOBS", ""))
    resolved: list[str] = []
    if globs:
        paths = assets.resolve_globs(
            source,
            globs,
            policy=os.environ.get("RELEASE_ASSET_IF_NO_FILES_FOUND", "error").strip(),
            field="release-asset",
        )
        resolved = _relative(paths)
    return title, body, resolved


def _resolve_body() -> str:
    notes = os.environ.get("RELEASE_NOTES", "")
    if notes.strip():
        return notes
    notes_file = os.environ.get("RELEASE_NOTES_FILE", "").strip()
    if not notes_file:
        return ""
    path = assets.contained_dir(notes_file, field="release-notes-file")
    if not path.is_file():
        raise SystemExit(f"release-notes-file does not exist: {notes_file}.")
    return path.read_text(encoding="utf-8")


def _resolve_zenodo(version: str) -> tuple[dict[str, object], list[str]]:
    source = _source_dir("ZENODO_ASSET_SOURCE_PATH", "zenodo-asset-source-path")
    globs = assets.parse_lines(os.environ.get("ZENODO_ASSET_GLOBS", ""))
    paths = assets.resolve_globs(
        source,
        globs,
        policy=os.environ.get("ZENODO_ASSET_IF_NO_FILES_FOUND", "error").strip(),
        field="zenodo-asset",
    )
    _verify_assets(paths, version)

    extra = metadata.validate_metadata_extra(os.environ.get("ZENODO_METADATA_EXTRA", ""))
    cff_path = os.environ.get("ZENODO_METADATA_CFF_PATH", "").strip()
    cff_data: dict[str, object] = {}
    if cff_path:
        cff_data = cff.load_cff(assets.contained_dir(cff_path, field="zenodo-metadata-cff-path"))

    meta = cff.build_metadata(
        cff=cff_data,
        title=os.environ.get("ZENODO_TITLE", ""),
        creators_raw=os.environ.get("ZENODO_CREATORS", ""),
        description=os.environ.get("ZENODO_DESCRIPTION", ""),
        upload_type=os.environ.get("ZENODO_UPLOAD_TYPE", "software").strip() or "software",
        version=version,
        license_id=os.environ.get("ZENODO_LICENSE", ""),
        keywords_raw=os.environ.get("ZENODO_KEYWORDS", ""),
        extra=extra,
    )
    return meta, _relative(paths)


def _verify_assets(paths: list[Path], version: str) -> None:
    raw = os.environ.get("PUBLISH_DIST_MANIFEST", "").strip()
    if not raw:
        return
    try:
        manifest_data = dist_manifest.parse_manifest(raw)
    except dist_manifest.ManifestError as error:
        raise SystemExit(str(error)) from error
    entries = dist_manifest.manifest_entries(manifest_data)
    on_disk = {path.name: path for path in paths}
    if len(on_disk) != len(paths):
        raise SystemExit("resolved Zenodo assets have duplicate filenames; refusing to upload.")
    unlisted = sorted(set(on_disk) - set(entries))
    if unlisted:
        raise SystemExit(
            f"Zenodo assets not covered by publish-dist-manifest: {', '.join(unlisted)}."
        )
    missing = sorted(set(entries) - set(on_disk))
    if missing:
        raise SystemExit(
            f"publish-dist-manifest lists files absent from the Zenodo assets: "
            f"{', '.join(missing)}."
        )
    for name, (sha256, size) in entries.items():
        try:
            hashing.compare_entry(on_disk[name], name, sha256, size)
        except hashing.DigestError as error:
            raise SystemExit(str(error)) from error
    versions = dist_manifest.manifest_versions(manifest_data)
    skew = sorted(item for item in versions if item != version)
    if skew:
        raise SystemExit(
            f"publish-dist-manifest version(s) {', '.join(skew)} do not match the "
            f"resolved version {version!r}."
        )


def _source_dir(env_name: str, field: str) -> Path:
    rel = (
        os.environ.get(env_name, "").strip() or os.environ.get("ARTIFACT_DOWNLOAD_PATH", "").strip()
    )
    return assets.contained_dir(rel, field=field)


def _relative(paths: list[Path]) -> list[str]:
    root = assets.workspace_root()
    relatives: list[str] = []
    for path in paths:
        try:
            relatives.append(path.resolve().relative_to(root).as_posix())
        except ValueError as error:
            raise SystemExit(f"resolved asset {path} escaped the workspace.") from error
    return relatives


def _asset_summary(heading: str, relatives: list[str]) -> list[str]:
    if not relatives:
        return [f"{heading}: none", ""]
    lines = [f"{heading}:", ""]
    lines += [f"- `{item}`" for item in relatives]
    lines.append("")
    return lines


def _strip_v(tag: str) -> str:
    return tag[1:] if tag[:1] in {"v", "V"} and tag[1:2].isdigit() else tag


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _emit_outputs(outputs: dict[str, str]) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            delimiter = f"ghadelim_{_secrets.token_hex(16)}"
            handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def _write_summary(lines: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
