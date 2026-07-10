"""File hashing and manifest digest comparison (prepare.py and reverify.py)."""

from __future__ import annotations

import hashlib
from pathlib import Path


class DigestError(ValueError):
    """A file failed sha256/size verification against the manifest."""


def hash_file(path: Path) -> tuple[str, int]:
    """Return ``(sha256_hex, size_bytes)`` for ``path``."""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def locate_by_name(base_dir: Path, name: str) -> Path:
    """Find exactly one regular file named ``name`` anywhere under ``base_dir``."""
    matches = [path for path in sorted(base_dir.rglob(name)) if path.is_file()]
    if not matches:
        raise DigestError(f"manifest lists {name!r} but it is missing from {base_dir}.")
    if len(matches) > 1:
        raise DigestError(
            f"manifest file {name!r} matches more than one file under {base_dir} (ambiguous)."
        )
    return matches[0]


def compare_entry(path: Path, name: str, expected_sha: str, expected_size: int) -> None:
    """Recompute ``path`` and fail loudly on a sha256 or size mismatch."""
    actual_sha, actual_size = hash_file(path)
    if actual_size != expected_size:
        raise DigestError(
            f"size mismatch for {name!r}: manifest {expected_size}, on disk {actual_size}."
        )
    if actual_sha != expected_sha:
        raise DigestError(
            f"sha256 mismatch for {name!r}: manifest {expected_sha}, on disk {actual_sha}."
        )


def verify_entries(base_dir: Path, entries: dict[str, tuple[str, int]]) -> list[str]:
    """Locate and byte-verify every manifest entry under ``base_dir`` (lean reverify)."""
    verified: list[str] = []
    for name in sorted(entries):
        expected_sha, expected_size = entries[name]
        path = locate_by_name(base_dir, name)
        compare_entry(path, name, expected_sha, expected_size)
        verified.append(name)
    return verified
