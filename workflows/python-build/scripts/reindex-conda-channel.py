"""Generate authoritative repodata.json for every subdir of a conda channel.

The python-build ``collect`` job merges each matrix leg's conda packages into a
single channel. Per-leg repodata only covers that leg's packages, so the merged
channel needs a fresh, authoritative index across every subdir.

Historically this shelled out to the conda organization's ``conda-index``, but
that package imports ``conda.models.version`` at import time — a hard runtime
dependency on the full ``conda`` package, which is *yanked* on PyPI (its newest
release, 4.3.16, predates Python 3.10 and no longer installs) and is not
distributed there at all in its modern form. Rather than drag conda into an
ephemeral environment, this script builds repodata.json directly: it is
deterministic, has no conda dependency, and needs only ``zstandard`` to
decompress the ``.conda`` inner tarball (delivered by the caller's
``uv run --with zstandard``).

A conda package record in repodata.json is exactly the package's
``info/index.json`` (name, version, build, build_number, depends, subdir,
license, timestamp, noarch, ...) augmented with the file's ``md5``, ``sha256``,
and ``size``. Legacy ``.tar.bz2`` packages hold ``info/index.json`` directly in a
bzip2 tarball (stdlib only); modern ``.conda`` packages are a zip whose
``info-*.tar.zst`` member is a zstd-compressed tarball carrying it.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

# conda-index emits repodata_version 1 with split packages/packages.conda maps;
# match that so existing conda clients read the merged channel unchanged.
REPODATA_VERSION = 1
INDEX_MEMBER = "info/index.json"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        raise SystemExit("usage: reindex-conda-channel.py <channel-dir>")
    channel = Path(argv[0]).resolve()
    if not channel.is_dir():
        raise SystemExit(f"channel directory does not exist: {channel}")
    for subdir in sorted(p for p in channel.iterdir() if p.is_dir()):
        _write_subdir_repodata(subdir)
    return 0


def _write_subdir_repodata(subdir: Path) -> None:
    """Write ``<subdir>/repodata.json`` describing every package in ``subdir``."""
    packages: dict[str, dict[str, Any]] = {}
    packages_conda: dict[str, dict[str, Any]] = {}
    for path in sorted(subdir.iterdir()):
        if not path.is_file():
            continue
        if path.name.endswith(".tar.bz2"):
            packages[path.name] = _record(path)
        elif path.name.endswith(".conda"):
            packages_conda[path.name] = _record(path)
    repodata = {
        "info": {"subdir": subdir.name},
        "packages": packages,
        "packages.conda": packages_conda,
        "removed": [],
        "repodata_version": REPODATA_VERSION,
    }
    # sort_keys makes the output byte-for-byte deterministic regardless of the
    # order the filesystem yields packages.
    (subdir / "repodata.json").write_text(
        json.dumps(repodata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _record(path: Path) -> dict[str, Any]:
    """A repodata record: the package's index.json plus md5/sha256/size."""
    data = path.read_bytes()
    record = dict(_read_index_json(path))
    record["md5"] = hashlib.md5(data).hexdigest()  # noqa: S324 - repodata contract, not security
    record["sha256"] = hashlib.sha256(data).hexdigest()
    record["size"] = len(data)
    return record


def _read_index_json(path: Path) -> dict[str, Any]:
    raw = _extract_index_bytes(path)
    try:
        index = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path.name}: {INDEX_MEMBER} is not valid JSON: {error}") from error
    if not isinstance(index, dict) or "name" not in index or "version" not in index:
        raise SystemExit(
            f"{path.name}: {INDEX_MEMBER} is missing the required name/version fields."
        )
    return index


def _extract_index_bytes(path: Path) -> bytes:
    if path.name.endswith(".tar.bz2"):
        return _extract_from_tar_bz2(path)
    return _extract_from_conda(path)


def _extract_from_tar_bz2(path: Path) -> bytes:
    """Read ``info/index.json`` from a legacy bzip2 conda package (stdlib only)."""
    try:
        with tarfile.open(path, "r:bz2") as archive:
            return _read_index_member(archive, path)
    except tarfile.TarError as error:
        raise SystemExit(
            f"{path.name}: cannot read package as a tar.bz2 archive: {error}"
        ) from error


def _extract_from_conda(path: Path) -> bytes:
    """Read ``info/index.json`` from a modern ``.conda`` (zip of zstd tarballs)."""
    # Imported lazily: the tar.bz2 path and the pure record logic need no zstd, so
    # the module stays importable (and unit-testable) without zstandard present.
    import zstandard

    try:
        with zipfile.ZipFile(path) as bundle:
            info_names = [
                name
                for name in bundle.namelist()
                if name.startswith("info-") and name.endswith(".tar.zst")
            ]
            if not info_names:
                raise SystemExit(f"{path.name}: no info-*.tar.zst entry in .conda package.")
            compressed = bundle.read(sorted(info_names)[0])
    except zipfile.BadZipFile as error:
        raise SystemExit(f"{path.name}: cannot read package as a .conda zip: {error}") from error

    decompressor = zstandard.ZstdDecompressor()
    buffer = io.BytesIO()
    with decompressor.stream_reader(io.BytesIO(compressed)) as reader:
        buffer.write(reader.read())
    buffer.seek(0)
    try:
        with tarfile.open(fileobj=buffer) as archive:
            return _read_index_member(archive, path)
    except tarfile.TarError as error:
        raise SystemExit(f"{path.name}: cannot read the .conda info tarball: {error}") from error


def _read_index_member(archive: tarfile.TarFile, path: Path) -> bytes:
    # extractfile raises KeyError when the member is absent and returns None when
    # it exists but is not a regular file; both mean the package has no usable
    # index.json, so fail loudly rather than index an incomplete channel.
    try:
        member = archive.extractfile(INDEX_MEMBER)
    except KeyError:
        member = None
    if member is None:
        raise SystemExit(f"{path.name}: {INDEX_MEMBER} not found in package.")
    return member.read()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
