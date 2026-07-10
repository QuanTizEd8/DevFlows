"""Charset, spec, and filename parsing for anaconda-publish (no I/O, no argv)."""

from __future__ import annotations

import re

# anaconda.org owners (users/orgs). The single blast-radius control: no spec ever
# carries an owner, so this is the only value that selects a namespace.
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# Channel labels (upload --label / move --to-label). No slashes/spaces/metachars.
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# conda package name and version segment grammars.
_PKG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")
_CONDA_EXTENSIONS = (".conda", ".tar.bz2")


class SpecError(ValueError):
    """A caller-supplied spec, owner, label, or argument failed validation."""


def validate_owner(owner: str) -> str:
    owner = owner.strip()
    if not owner:
        raise SpecError("publish-owner is required and must be non-empty.")
    if not _OWNER_RE.match(owner):
        raise SpecError(
            "publish-owner must be an anaconda.org user or organization "
            "(letters, digits, '_', '-', leading alphanumeric); got "
            f"{owner!r}."
        )
    return owner


def validate_label(label: str, *, field: str) -> str:
    label = label.strip()
    if not label:
        raise SpecError(f"{field} is required and must be non-empty.")
    if not _LABEL_RE.match(label):
        raise SpecError(
            f"{field} must be a safe channel label "
            "(letters, digits, '.', '_', '-', leading alphanumeric); got "
            f"{label!r}."
        )
    return label


def parse_spec(spec: str) -> tuple[str, ...]:
    """Validate a caller spec (``package/version[/filename]``, never an owner).

    A three-segment spec is accepted only when its third segment is a conda
    filename; any other three-segment shape is rejected as a smuggled owner.
    """
    raw = spec.strip()
    if not raw:
        raise SpecError("spec must be non-empty.")
    segments = raw.split("/")
    if len(segments) not in (2, 3):
        raise SpecError(
            f"spec {spec!r} must be package/version[/filename] without an owner "
            "segment (2 or 3 segments only)."
        )
    package, version = segments[0], segments[1]
    if not _PKG_RE.match(package):
        raise SpecError(f"spec {spec!r} has an invalid package segment {package!r}.")
    if not _VERSION_RE.match(version):
        raise SpecError(f"spec {spec!r} has an invalid version segment {version!r}.")
    if len(segments) == 3:
        filename = segments[2]
        if not filename.endswith(_CONDA_EXTENSIONS):
            raise SpecError(
                f"spec {spec!r} must be package/version[/filename] without an owner "
                "segment; a three-segment spec is only valid when the third segment "
                "is a package filename ending in .conda or .tar.bz2."
            )
        if not _conda_filename_re().match(filename):
            raise SpecError(f"spec {spec!r} has an invalid filename segment {filename!r}.")
    return tuple(segments)


def parse_spec_list(raw: str) -> list[str]:
    """Split a newline-separated spec block into non-empty, stripped specs."""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def validate_spec_list(raw: str, *, field: str) -> list[str]:
    """Validate every spec in a newline block; return the cleaned specs."""
    specs = parse_spec_list(raw)
    if not specs:
        raise SpecError(f"{field} is required and must list at least one spec.")
    for spec in specs:
        try:
            parse_spec(spec)
        except SpecError as error:
            raise SpecError(f"{field}: {error}") from error
    return specs


def owner_qualified(owner: str, spec: str) -> str:
    """Prepend the (already validated) owner to a (validated) spec."""
    return f"{owner}/{spec}"


def _conda_filename_re() -> re.Pattern[str]:
    return re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*\.(conda|tar\.bz2)$")


def parse_conda_filename(filename: str) -> tuple[str, str]:
    """Return ``(package, version)`` parsed from a conda package filename.

    conda filenames are ``<name>-<version>-<build>.<ext>``; the name itself may
    contain hyphens, so the version and build are split from the right.
    """
    if filename.endswith(".conda"):
        stem = filename[: -len(".conda")]
    elif filename.endswith(".tar.bz2"):
        stem = filename[: -len(".tar.bz2")]
    else:
        raise SpecError(
            f"{filename!r} is not a conda package (expected a .conda or .tar.bz2 file)."
        )
    segments = stem.rsplit("-", 2)
    if len(segments) != 3 or not all(segments):
        raise SpecError(
            f"cannot parse name and version from conda filename {filename!r} "
            "(expected <name>-<version>-<build>)."
        )
    return segments[0], segments[1]
