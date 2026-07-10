"""dist-manifest entry extraction (light: no file I/O, no hashing)."""

from __future__ import annotations

from parsing import SpecError


def conda_manifest_entries(manifest: dict[str, object]) -> dict[str, tuple[str, int]]:
    """Return ``{name: (sha256, size)}`` for every kind=conda manifest entry."""
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SpecError("dist manifest 'files' must be a list.")
    entries: dict[str, tuple[str, int]] = {}
    for item in files:
        if not isinstance(item, dict) or item.get("kind") != "conda":
            continue
        name = str(item.get("name") or "")
        sha256 = str(item.get("sha256") or "")
        size = item.get("size")
        if not name or not sha256 or not isinstance(size, int):
            raise SpecError(f"dist manifest conda entry is incomplete: {item!r}.")
        entries[name] = (sha256, int(size))
    return entries


def manifest_kinds(manifest: dict[str, object]) -> dict[str, str]:
    """Return ``{name: kind}`` across all manifest files (for wrong-kind detection)."""
    files = manifest.get("files")
    kinds: dict[str, str] = {}
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict) and item.get("name"):
                kinds[str(item["name"])] = str(item.get("kind") or "")
    return kinds
