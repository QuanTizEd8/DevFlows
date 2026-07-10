"""Charset, reference, and argument parsing for binder-build (no I/O, no argv run).

Shared by validate-inputs.py (validate job) and build-binder.py (build job) so the
repo2docker-arguments ALLOWLIST is enforced identically at validation time and again
when the build job reconstructs the argv. Push-image.py is deliberately self-contained
(it does not import this module) to keep the credentialed push job's inlined footprint
lean, mirroring anaconda-publish's reverify split.
"""

from __future__ import annotations

import re
import shlex

# Internal build tag applied to the locally-built image. The build job saves the
# image as image-name:INTERNAL_BUILD_TAG and the push job loads and re-tags from it,
# so the two jobs must agree on this literal (also set in the workflow env).
INTERNAL_BUILD_TAG = "devflows-binder-build"

# Practical subset of the distribution image-reference grammar, name segment only.
# Docker/OCI names are lowercase; ghcr.io and Docker Hub both reject uppercase.
_ALNUM = r"[a-z0-9]+"
_SEPARATOR = r"(?:[._]|__|[-]+)"
_PATH_COMPONENT = rf"{_ALNUM}(?:{_SEPARATOR}{_ALNUM})*"
_NAME = rf"{_PATH_COMPONENT}(?:/{_PATH_COMPONENT})*"
_DOMAIN_COMPONENT = r"(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])"
_DOMAIN = rf"{_DOMAIN_COMPONENT}(?:\.{_DOMAIN_COMPONENT})*(?::[0-9]+)?"
# image-name is a reference WITHOUT a tag or digest: a name path segment does not
# contain ':' or '@', and a domain's ':' is only a port before the first '/'.
_IMAGE_NAME_RE = re.compile(rf"^(?:{_DOMAIN}/)?{_NAME}$")

# A single Docker tag token (also used for the optional commit-SHA tag once the
# prefix is prepended).
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
# A tag PREFIX: first char tag-legal, then tag-legal chars, short enough that
# prefix + a 40-char git SHA still fits the 128-char tag limit.
_TAG_PREFIX_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,87}$")
# jupyter-repo2docker uses date-based versions (YYYY.MM.PATCH); reject anything that
# smuggles a specifier, extras, or shell metacharacters.
_VERSION_RE = re.compile(r"^[0-9]{4}\.[0-9]{1,2}\.[0-9]+$")
# GitHub artifact names disallow many characters; keep to a conservative safe token.
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# mybinder provider slugs in the /build/<provider>/<repo>/<ref> URL.
_PROVIDERS = ("gh", "gl", "git", "gist", "zenodo", "figshare", "hydroshare", "dataverse")

# repo2docker-arguments is guarded by a strict ALLOWLIST grounded in repo2docker's
# argparse (repo2docker/__main__.py). A denylist is not acceptable: argparse accepts
# --flag=value, attached short options (-e X, -v X, -p X), and bare positionals, so an
# owned flag (--image-name, --push/--no-push, --no-run/--run, --no-build/--build,
# --ref, and the positional repo source) can be smuggled past exact-token rejection.
# Only genuinely-safe passthrough flags that cannot change the image identity, the
# push behavior, the build/run control, or the source are allowed.
_ALLOWED_BOOL_FLAGS = frozenset({"--debug", "--no-clean", "--json-logs"})
_ALLOWED_VALUE_FLAGS = frozenset({"--build-arg", "--label"})


class SpecError(ValueError):
    """A caller-supplied input failed validation."""


def validate_image_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise SpecError("image-name is required and must be non-empty.")
    if not _IMAGE_NAME_RE.match(value):
        raise SpecError(
            "image-name must be a lowercase [registry/]name reference WITHOUT a tag or "
            f"digest (e.g. ghcr.io/owner/repo-binder); got {value!r}."
        )
    return value


def validate_tag_list(raw: str, *, field: str) -> list[str]:
    tags = [line.strip() for line in raw.splitlines() if line.strip()]
    if not tags:
        raise SpecError(f"{field} must resolve to a non-empty newline-separated list of tags.")
    for tag in tags:
        if not _TAG_RE.match(tag):
            raise SpecError(f"{field} contains an invalid Docker tag {tag!r}.")
    return tags


def validate_tag_prefix(value: str, *, field: str) -> str:
    value = value.strip()
    if not value:
        raise SpecError(f"{field} is required and must be non-empty when the SHA tag is enabled.")
    if not _TAG_PREFIX_RE.match(value):
        raise SpecError(
            f"{field} must be a safe tag prefix (leading alphanumeric or '_', then letters, "
            f"digits, '.', '_', '-') short enough to prepend to a commit SHA; got {value!r}."
        )
    return value


def validate_source_path(value: str, *, field: str) -> str:
    value = value.strip()
    if not value:
        raise SpecError(f"{field} is required and must be non-empty.")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise SpecError(
            f"{field} must be a workspace-relative path without '..' or a leading '/'; "
            f"got {value!r}."
        )
    return value


def validate_version(value: str, *, field: str) -> str:
    value = value.strip()
    if not value:
        raise SpecError(f"{field} is required and must be non-empty.")
    if not _VERSION_RE.match(value):
        raise SpecError(
            f"{field} must be a date-based jupyter-repo2docker version (YYYY.MM.PATCH, e.g. "
            f"2026.4.0); got {value!r}. Extras and specifiers are not allowed."
        )
    return value


def validate_artifact_name(value: str, *, field: str) -> str:
    value = value.strip()
    if not value:
        raise SpecError(f"{field} is required and must be non-empty.")
    if not _ARTIFACT_NAME_RE.match(value):
        raise SpecError(
            f"{field} must be an artifact-safe token (letters, digits, '.', '_', '-', leading "
            f"alphanumeric); got {value!r}."
        )
    return value


def validate_provider(value: str, *, field: str) -> str:
    value = value.strip()
    if value not in _PROVIDERS:
        raise SpecError(f"{field} must be one of {', '.join(_PROVIDERS)}; got {value!r}.")
    return value


def validate_https_url(value: str, *, field: str) -> str:
    value = value.strip()
    if not value.startswith("https://") or len(value) <= len("https://"):
        raise SpecError(f"{field} must be an https:// URL; got {value!r}.")
    return value


def validate_non_empty(value: str, *, field: str) -> str:
    value = value.strip()
    if not value:
        raise SpecError(f"{field} is required and must be non-empty.")
    return value


def parse_repo2docker_arguments(raw: str, *, field: str) -> list[str]:
    """shlex-split repo2docker-arguments and accept ONLY allowlisted passthrough flags."""
    try:
        args = shlex.split(raw)
    except ValueError as error:
        raise SpecError(f"{field} could not be parsed as shell arguments: {error}.") from error
    for arg in args:
        _validate_argument(arg, field=field)
    return args


def _allowed_flags_display() -> str:
    return ", ".join(sorted(_ALLOWED_BOOL_FLAGS | _ALLOWED_VALUE_FLAGS))


def _reject(arg: str, *, field: str) -> None:
    raise SpecError(
        f"{field} may not contain {arg!r}: only the allowlisted passthrough flags "
        f"({_allowed_flags_display()}) are accepted (--flag or --flag=value). The image "
        "name, tags, push behavior, build/run control (--image-name, --push/--no-push, "
        "--no-run, --no-build), the ref, and the positional source path are owned by typed "
        "inputs, never this input."
    )


def _validate_argument(arg: str, *, field: str) -> None:
    # A token that is not a long option is either a bare positional (the repo source,
    # owned by repo2docker-source-path) or an attached short option (-e, -v, -p, ...),
    # both of which the allowlist rejects outright.
    if not arg.startswith("--"):
        _reject(arg, field=field)
    flag, sep, value = arg.partition("=")
    if flag in _ALLOWED_BOOL_FLAGS:
        if sep:
            raise SpecError(f"{field}: {flag} is a boolean flag and takes no value; got {arg!r}.")
        return
    if flag in _ALLOWED_VALUE_FLAGS:
        if not sep or not value:
            raise SpecError(
                f"{field}: {flag} requires a value written as {flag}=VALUE; got {arg!r}."
            )
        return
    _reject(arg, field=field)
