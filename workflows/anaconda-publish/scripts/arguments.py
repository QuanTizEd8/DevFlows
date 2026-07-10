"""upload-arguments hardening: a strict allowlist over ``anaconda upload`` flags."""

from __future__ import annotations

import shlex

from parsing import SpecError

# upload-arguments is guarded by a strict ALLOWLIST, never a denylist: argparse
# defeats denylists via attached short values, long-flag abbreviations, and bare
# positionals. Only cosmetic/metadata flags that cannot change the upload's
# namespace, identity, collision handling, or file selection are accepted.
_ALLOWED_UPLOAD_BOOL_FLAGS = frozenset(
    {"--no-progress", "--no-register", "--register", "--keep-basename"}
)
_ALLOWED_UPLOAD_VALUE_FLAGS = frozenset({"--summary", "--description"})

# upload-existing-mode enum. 'fail' passes neither flag (anaconda-client errors).
EXISTING_MODES = ("fail", "skip", "overwrite")


def parse_extra_arguments(raw: str, *, field: str) -> list[str]:
    """shlex-split upload-arguments and accept ONLY allowlisted metadata flags."""
    try:
        args = shlex.split(raw)
    except ValueError as error:
        raise SpecError(f"{field} could not be parsed as shell arguments: {error}.") from error
    for arg in args:
        _validate_upload_argument(arg, field=field)
    return args


def _allowed_upload_flags_display() -> str:
    return ", ".join(sorted(_ALLOWED_UPLOAD_BOOL_FLAGS | _ALLOWED_UPLOAD_VALUE_FLAGS))


def _reject(arg: str, *, field: str) -> None:
    raise SpecError(
        f"{field} may not contain {arg!r}: only the allowlisted metadata flags "
        f"({_allowed_upload_flags_display()}) are accepted (--flag or --flag=value). "
        "The owner, label, version, collision mode, token, site, and file paths are "
        "owned by typed inputs, never this input."
    )


def _validate_upload_argument(arg: str, *, field: str) -> None:
    if not arg.startswith("--"):
        _reject(arg, field=field)
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
    _reject(arg, field=field)


def validate_existing_mode(mode: str) -> str:
    mode = mode.strip()
    if mode not in EXISTING_MODES:
        raise SpecError(
            f"upload-existing-mode must be one of {', '.join(EXISTING_MODES)}; got {mode!r}."
        )
    return mode
