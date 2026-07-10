"""upload-arguments hardening: a strict allowlist over ``anaconda upload`` flags."""

from __future__ import annotations

import shlex

from parsing import SpecError

# upload-arguments is guarded by a strict ALLOWLIST, never a denylist: argparse
# defeats denylists via attached short values (``-lmain`` -> ``-l main``), long-flag
# abbreviations (``--lab main`` -> ``--label main``), and bare positional file paths.
# Only cosmetic / package-metadata flags that cannot change the upload's namespace,
# identity, collision handling, or file selection are accepted. Everything DevFlows
# owns (owner, label, version, package, collision mode, token, site, paths) is
# rejected here and supplied from typed inputs and the anaconda-token secret.
_ALLOWED_UPLOAD_BOOL_FLAGS = frozenset(
    {"--no-progress", "--no-register", "--register", "--keep-basename"}
)
_ALLOWED_UPLOAD_VALUE_FLAGS = frozenset({"--summary", "--description"})

# upload-existing-mode enum. 'fail' passes neither flag (anaconda-client errors).
EXISTING_MODES = ("fail", "skip", "overwrite")


def parse_extra_arguments(raw: str, *, field: str) -> list[str]:
    """shlex-split upload-arguments and accept ONLY allowlisted metadata flags.

    Every token must be exactly ``--flag`` (a known boolean) or ``--flag=value`` (a
    known value flag with a non-empty value). Anything else is rejected.
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
