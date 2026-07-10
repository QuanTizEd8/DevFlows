"""schema-1 dist-manifest parsing (no file I/O, no hashing).

Shared by prepare.py and the credentialed reverify.py; validate does its own cheap
shape gate inline so this heavier parser is inlined into two jobs, not three.
"""

from __future__ import annotations

import json
import re

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """A publish-dist-manifest value failed structural validation."""


def parse_manifest(raw: str) -> dict[str, object]:
    raw = raw.strip()
    if not raw:
        raise ManifestError("publish-dist-manifest is empty.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ManifestError(f"publish-dist-manifest is not valid JSON: {error}.") from error
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ManifestError('publish-dist-manifest must be a schema-1 object ({"schema": 1, ...}).')
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ManifestError("publish-dist-manifest 'files' must be a non-empty list.")
    for item in files:
        _validate_entry(item)
    return data


def _validate_entry(item: object) -> None:
    if not isinstance(item, dict):
        raise ManifestError("each publish-dist-manifest file entry must be an object.")
    name = item.get("name")
    sha256 = item.get("sha256")
    size = item.get("size")
    if not isinstance(name, str) or not name:
        raise ManifestError(f"publish-dist-manifest entry has an invalid name: {item!r}.")
    if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
        raise ManifestError(f"publish-dist-manifest entry {name!r} has an invalid sha256.")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ManifestError(f"publish-dist-manifest entry {name!r} has an invalid size.")


def manifest_entries(manifest: dict[str, object]) -> dict[str, tuple[str, int]]:
    """Return ``{name: (sha256, size)}`` for every manifest file entry."""
    entries: dict[str, tuple[str, int]] = {}
    files = manifest.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict):
                name = str(item.get("name") or "")
                sha256 = str(item.get("sha256") or "")
                size = item.get("size")
                if name and sha256 and isinstance(size, int):
                    entries[name] = (sha256, int(size))
    return entries


def manifest_versions(manifest: dict[str, object]) -> set[str]:
    """Distinct non-empty per-entry ``version`` values (for skew detection)."""
    versions: set[str] = set()
    files = manifest.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict):
                version = str(item.get("version") or "").strip()
                if version:
                    versions.add(version)
    return versions
