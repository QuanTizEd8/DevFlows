"""Bidirectional digest verification of on-disk conda files against the manifest."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from manifest import conda_manifest_entries, manifest_kinds
from parsing import SpecError, parse_conda_filename


@dataclass(frozen=True)
class CondaFile:
    """A verified ``.conda``/``.tar.bz2`` distribution file."""

    name: str
    path: Path
    sha256: str
    size: int
    version: str
    package: str


def _scan_conda_files(dist_path: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for pattern in ("*.conda", "*.tar.bz2"):
        for path in sorted(dist_path.rglob(pattern)):
            if not path.is_file():
                continue
            if path.name in found:
                raise SpecError(
                    f"conda file {path.name!r} appears more than once under "
                    f"{dist_path} (ambiguous across subdirectories)."
                )
            found[path.name] = path
    return found


def verify_files_against_manifest(dist_path: Path, manifest: dict[str, object]) -> list[CondaFile]:
    """Bidirectionally verify the on-disk conda files against the manifest.

    Every kind=conda manifest entry must have a file on disk whose recomputed
    sha256 AND size match, and every conda file on disk must be a kind=conda
    manifest entry. Any missing/unlisted/wrong-kind file or digest/size mismatch
    fails loudly naming the offending file.
    """
    if not dist_path.is_dir():
        raise SpecError(f"distribution path {dist_path} does not exist or is not a directory.")
    entries = conda_manifest_entries(manifest)
    if not entries:
        raise SpecError("dist manifest contains no conda packages.")
    kinds = manifest_kinds(manifest)
    on_disk = _scan_conda_files(dist_path)

    for name in sorted(on_disk):
        if name in entries:
            continue
        if name in kinds and kinds[name] != "conda":
            raise SpecError(
                f"conda file {name!r} is listed in the dist manifest as kind "
                f"{kinds[name]!r}, not 'conda'."
            )
        raise SpecError(
            f"conda file {name!r} was downloaded but is not listed in the dist manifest."
        )

    verified: list[CondaFile] = []
    for name in sorted(entries):
        expected_sha, expected_size = entries[name]
        if name not in on_disk:
            raise SpecError(
                f"dist manifest lists conda file {name!r} but it is missing from {dist_path}."
            )
        path = on_disk[name]
        data = path.read_bytes()
        actual_size = len(data)
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_size != expected_size:
            raise SpecError(
                f"size mismatch for {name!r}: manifest {expected_size}, on disk {actual_size}."
            )
        if actual_sha != expected_sha:
            raise SpecError(
                f"sha256 mismatch for {name!r}: manifest {expected_sha}, on disk {actual_sha}."
            )
        package, version = parse_conda_filename(name)
        verified.append(
            CondaFile(
                name=name,
                path=path,
                sha256=actual_sha,
                size=actual_size,
                version=version,
                package=package,
            )
        )
    return verified


def resolve_version(files: list[CondaFile], *, expected: str = "") -> str:
    """Cross-check a single consistent version, honoring an expected-version guard."""
    versions = sorted({item.version for item in files})
    if len(versions) != 1:
        detail = ", ".join(f"{item.name}={item.version}" for item in files)
        raise SpecError(
            f"verified conda packages disagree on version ({detail}); refusing to "
            "publish a mixed-version set."
        )
    version = versions[0]
    expected = expected.strip()
    if expected and version != expected:
        raise SpecError(
            f"publish-expected-version {expected!r} does not match the verified "
            f"package version {version!r}."
        )
    return version
