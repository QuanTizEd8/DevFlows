"""Shared pure helpers for the anaconda-publish workflow scripts.

Every mutating operation this workflow performs is built as an explicit argv
list (never a shell string) from validated pieces, so this module is the single
home for spec parsing, filename parsing, charset validation, digest verification,
and argv construction. It is imported by ``validate-inputs.py``, ``verify-dist.py``
and ``upload.py`` (each of those job steps carries a ``${DEVFLOWS_SCRIPT_ROOT}/
anaconda-publish/specs.py`` comment so the sync materialize step inlines it next
to its importer, exactly like python-build's collect.py/reindex sibling), and it
is unit-tested directly.
"""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

# Pinned default anaconda-client version installed (ephemerally, via `uvx --from`)
# on the credentialed jobs when publish-client-version is empty. Registered for
# Renovate via a custom pep440 manager in renovate.json5 (keyed on the inline
# `# renovate:` comment below); tests/test_anaconda_publish.py asserts the
# manager regex still matches this constant so the pin stays auto-updated.
# renovate: datasource=pypi depName=anaconda-client
ANACONDA_CLIENT_VERSION = "1.13.0"

# anaconda.org owners (users/orgs): a leading alphanumeric then alphanumerics,
# hyphen, underscore. The single blast-radius control -- no spec ever carries an
# owner, so this is the only value that selects a namespace.
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# Channel labels (anaconda upload --label / move --to-label). Conservative safe
# set; no slashes, spaces, or shell metacharacters.
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# conda package name and version segment grammars. Names use the conda safe set;
# versions additionally allow '+' and '!' (local/epoch separators).
_PKG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")
_CONDA_EXTENSIONS = (".conda", ".tar.bz2")

# upload-arguments is guarded by a strict ALLOWLIST, never a denylist. `anaconda
# upload` is argparse-based, so a denylist of owned flags is inherently bypassable:
# argparse accepts attached short values (``-lmain`` parses as ``-l main``), unique
# long-flag abbreviations (``--lab main`` parses as ``--label main``), and bare
# positional file paths (an unverified ``.conda`` would ride the credentialed
# upload). Only cosmetic / package-metadata flags that cannot change the upload's
# target namespace, package/version identity, collision handling, or file selection
# are allowed. Everything DevFlows owns is rejected here and supplied from typed
# inputs and the anaconda-token secret instead: the owner (-u/--user), label
# (-l/--label, -c/--channel), version (-v/--version), package (-p/--package), the
# collision-mode group (--force/--skip-existing/-f/--fail/-i/--interactive/
# -m/--force-metadata-update), the internal --build-id, the global token (-t/--token)
# and site (-s/--site), and the file paths. Audited against `anaconda upload --help`
# at ANACONDA_CLIENT_VERSION (1.13.0): at the upload subparser -s is --summary and -t
# is --package-type (the token/site short flags live on the global parser), a further
# reason the old letter-based denylist was unsound.
_ALLOWED_UPLOAD_BOOL_FLAGS = frozenset(
    {"--no-progress", "--no-register", "--register", "--keep-basename"}
)
_ALLOWED_UPLOAD_VALUE_FLAGS = frozenset({"--summary", "--description"})

# upload-existing-mode enum mapped onto anaconda-client's mutually-exclusive mode
# group. 'fail' passes neither flag (anaconda-client errors on a collision).
EXISTING_MODES = ("fail", "skip", "overwrite")
_EXISTING_MODE_FLAGS = {"fail": [], "skip": ["--skip-existing"], "overwrite": ["--force"]}


class SpecError(ValueError):
    """A caller-supplied spec, owner, label, or argument failed validation."""


@dataclass(frozen=True)
class CondaFile:
    """A verified ``.conda``/``.tar.bz2`` distribution file."""

    name: str
    path: Path
    sha256: str
    size: int
    version: str
    package: str


# --------------------------------------------------------------------------- #
# Charset validation                                                           #
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Spec parsing                                                                 #
# --------------------------------------------------------------------------- #
def parse_spec(spec: str) -> tuple[str, ...]:
    """Validate a caller spec and return its segments.

    Accepts ``package/version`` or ``package/version/filename`` ONLY. A spec must
    never carry an owner segment (the owner comes solely from publish-owner), so a
    three-segment spec is accepted only when its third segment is a conda package
    filename (ends in .conda or .tar.bz2); any other three-segment shape is
    rejected as a smuggled owner. Returns the validated segments (no owner).
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
            # A 3-segment spec whose third piece is not a conda filename is an
            # owner-qualified spec (owner/package/version); reject it loudly.
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


# --------------------------------------------------------------------------- #
# Filename parsing                                                             #
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# upload-arguments hardening                                                   #
# --------------------------------------------------------------------------- #
def parse_extra_arguments(raw: str, *, field: str) -> list[str]:
    """shlex-split upload-arguments and accept ONLY allowlisted metadata flags.

    Strict allowlist form: every token must be exactly ``--flag`` (a known boolean
    flag) or ``--flag=value`` (a known value-taking flag with a non-empty value). A
    token that does not start with ``--`` (a bare positional, a single-dash short
    option, or an attached short value such as ``-lmain``), an unknown or abbreviated
    long flag, or a mis-shaped allowlisted flag is rejected: `anaconda upload`'s
    argparse would otherwise let it override the owner/label/version/collision-mode
    or ride an unverified file onto the credentialed upload.
    """
    try:
        args = shlex.split(raw)
    except ValueError as error:
        raise SpecError(f"{field} could not be parsed as shell arguments: {error}.") from error
    for arg in args:
        _validate_upload_argument(arg, field=field)
    return args


def _allowed_upload_flags_display() -> str:
    return ", ".join(sorted(_ALLOWED_UPLOAD_BOOL_FLAGS | _ALLOWED_UPLOAD_VALUE_FLAGS))


def _validate_upload_argument(arg: str, *, field: str) -> None:
    if not arg.startswith("--"):
        raise SpecError(
            f"{field} may not contain {arg!r}: only the allowlisted metadata flags "
            f"({_allowed_upload_flags_display()}) are accepted, each written as --flag "
            "or --flag=value. Bare file paths, single-dash short options, and attached "
            "short values are rejected because the owner, label, version, collision "
            "mode, token, site, and file paths are owned by typed inputs and supplied "
            "by DevFlows, never through this input."
        )
    flag, sep, value = arg.partition("=")
    if flag in _ALLOWED_UPLOAD_BOOL_FLAGS:
        if sep:
            raise SpecError(f"{field}: {flag} is a boolean flag and takes no value; got {arg!r}.")
        return
    if flag in _ALLOWED_UPLOAD_VALUE_FLAGS:
        if not sep or not value:
            raise SpecError(
                f"{field}: {flag} requires a value written as {flag}=VALUE; got {arg!r}."
            )
        return
    raise SpecError(
        f"{field} may not contain {arg!r}: only the allowlisted metadata flags "
        f"({_allowed_upload_flags_display()}) are accepted. The owner, label, version, "
        "collision mode, token, site, and file paths are owned by typed inputs and "
        "supplied by DevFlows, never through this input."
    )


def validate_existing_mode(mode: str) -> str:
    mode = mode.strip()
    if mode not in EXISTING_MODES:
        raise SpecError(
            f"upload-existing-mode must be one of {', '.join(EXISTING_MODES)}; got {mode!r}."
        )
    return mode


# --------------------------------------------------------------------------- #
# Digest verification                                                          #
# --------------------------------------------------------------------------- #
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
    manifest entry. A missing file, an unlisted file, a wrong-kind file, a digest
    mismatch, or a size mismatch each fails loudly naming the offending file.
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


# --------------------------------------------------------------------------- #
# argv construction                                                            #
# --------------------------------------------------------------------------- #
def anaconda_base(server_url: str) -> list[str]:
    argv = ["anaconda"]
    server_url = server_url.strip()
    if server_url:
        argv += ["-s", server_url]
    return argv


def build_upload_argv(
    *,
    server_url: str,
    owner: str,
    label: str,
    mode: str,
    extra_arguments: list[str],
    file_path: str,
) -> list[str]:
    return (
        anaconda_base(server_url)
        + ["upload", "--user", owner, "--label", label]
        + list(_EXISTING_MODE_FLAGS[mode])
        + list(extra_arguments)
        + [file_path]
    )


def build_move_argv(*, server_url: str, from_label: str, to_label: str, target: str) -> list[str]:
    return anaconda_base(server_url) + [
        "move",
        "--from-label",
        from_label,
        "--to-label",
        to_label,
        target,
    ]


def build_remove_argv(*, server_url: str, target: str) -> list[str]:
    return anaconda_base(server_url) + ["remove", "--force", target]


def uvx_wrap(client_version: str, argv: list[str]) -> list[str]:
    """Wrap an anaconda-client argv in an ephemeral, pinned `uvx --from` runner."""
    return ["uvx", "--from", f"anaconda-client=={client_version}", *argv]


def resolve_client_version(override: str) -> str:
    """The anaconda-client version to install: an explicit override or the pin."""
    override = override.strip()
    return override or ANACONDA_CLIENT_VERSION
