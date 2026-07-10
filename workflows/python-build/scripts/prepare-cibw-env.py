from __future__ import annotations

import os
import re
from pathlib import Path

# Same narrow grammar validate-inputs.py enforces on the matrix. Re-checked here
# because the values arrive at runtime via fromJSON(matrix) and are about to be
# written to $GITHUB_ENV, where a newline or stray control character could forge
# additional environment variables. Belt-and-braces with the validate gate.
_CIBW_SELECTOR = re.compile(r"^[A-Za-z0-9_.*?\- ]+$")


def main() -> int:
    """Export CIBW_BUILD / CIBW_ARCHS from the matrix leg, only when present.

    cibuildwheel treats an *empty* CIBW_BUILD as "match nothing", so passing the
    matrix values through step-level env unconditionally would turn a leg that
    omits them into a silent no-op build. Writing them to $GITHUB_ENV only when
    non-empty keeps cibuildwheel on its documented defaults (or the leg's `only`
    selector) otherwise.
    """
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        raise SystemExit("GITHUB_ENV is not set; cannot export cibuildwheel selectors.")

    exports: list[tuple[str, str]] = []
    for env_name, matrix_field in (("CIBW_BUILD", "MATRIX_BUILD"), ("CIBW_ARCHS", "MATRIX_ARCHS")):
        value = os.environ.get(matrix_field, "").strip()
        if not value:
            continue
        if not _CIBW_SELECTOR.match(value):
            raise SystemExit(
                f"{matrix_field} contains unsupported characters: {value!r}. "
                "Allowed: letters, digits, '_', '.', '-', '*', '?', and spaces."
            )
        exports.append((env_name, value))

    with Path(github_env).open("a", encoding="utf-8") as handle:
        for env_name, value in exports:
            handle.write(f"{env_name}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
