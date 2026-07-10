from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Base host per index. The install pulls the exact-pinned target from the
# selected index; for TestPyPI, PyPI is added as an EXTRA index for dependency
# resolution only (TestPyPI does not mirror dependencies), while the target
# package stays exact-version-pinned and is found on the primary index.
_INDEX_BASE = {
    "pypi": "https://pypi.org",
    "testpypi": "https://test.pypi.org",
}
# install-check-arguments is a strict ALLOWLIST of pip/uv *build-mode* flags, kept
# byte-identical to validate-inputs.py (defense-in-depth if this script is ever run
# outside the workflow). The install target is exact-pinned ({name}=={version}) and
# the index is chosen solely by publish-index, so a caller has no legitimate reason
# to select an index, add a requirement file, or name another package. A denylist of
# index flags is bypassable (uv/pip expose -i/--index-url/--extra-index-url/--index/
# --default-index/-f/--find-links/--no-index/--index-strategy plus attached -i.../-f...
# forms); only these build-mode flags are accepted, everything else is rejected.
_ALLOWED_INSTALL_BOOL_FLAGS = frozenset({"--no-deps"})
_ALLOWED_INSTALL_VALUE_FLAGS = frozenset({"--no-binary", "--only-binary"})
_POLL_INTERVAL_SECONDS = 15


def main() -> int:
    index = _require("PUBLISH_INDEX")
    if index not in _INDEX_BASE:
        raise SystemExit(f"unknown publish-index {index!r}; expected 'pypi' or 'testpypi'.")
    name = _require("PACKAGE_NAME")
    version = _require("PACKAGE_VERSION")
    import_names = _parse_list(os.environ.get("INSTALL_CHECK_IMPORT_NAMES", ""))
    extra_args = _parse_arguments(os.environ.get("INSTALL_CHECK_ARGUMENTS", ""))
    timeout_minutes = _parse_timeout(os.environ.get("INSTALL_CHECK_TIMEOUT_MINUTES", "15"))

    deadline = time.monotonic() + timeout_minutes * 60
    _wait_for_version(index, name, version, deadline)

    workdir = Path(os.environ.get("RUNNER_TEMP") or ".").resolve() / "devflows-install-check"
    venv_python = _create_venv(workdir)
    _install(index, name, version, extra_args, venv_python)
    _import_check(venv_python, import_names)
    print(f"install-check passed: {name}=={version} installed from {index} and imported.")
    return 0


# --- pure helpers (unit-tested) --------------------------------------------- #


def version_json_url(index: str, name: str, version: str) -> str:
    """PyPI/TestPyPI JSON API URL that returns 200 once <name>==<version> exists."""
    return f"{_INDEX_BASE[index]}/pypi/{name}/{version}/json"


def simple_index_url(index: str) -> str:
    return f"{_INDEX_BASE[index]}/simple"


def build_install_command(
    index: str, name: str, version: str, extra_args: list[str], venv_python: str
) -> list[str]:
    command = ["uv", "pip", "install", "--python", venv_python]
    command += ["--index-url", simple_index_url(index)]
    if index == "testpypi":
        # PyPI as an EXTRA index resolves dependencies TestPyPI does not mirror;
        # the exact-pinned target still comes from TestPyPI (the primary index).
        command += ["--extra-index-url", simple_index_url("pypi")]
    command += extra_args
    command.append(f"{name}=={version}")
    return command


def _parse_list(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _parse_arguments(raw: str) -> list[str]:
    try:
        tokens = shlex.split(raw)
    except ValueError as error:
        raise SystemExit(f"install-check-arguments is not valid shell syntax: {error}.") from None
    _validate_install_arguments(tokens)
    return tokens


def _install_arguments_error(token: str) -> str:
    return (
        "install-check-arguments only accepts build-mode flags "
        f"(--no-binary, --only-binary, --no-deps); {token!r} is not allowed. Index "
        "selection (-i/--index-url/--extra-index-url/--index/--default-index/-f/"
        "--find-links/--no-index/--index-strategy), --requirement/-r, and bare package "
        "names are rejected: the index is chosen by publish-index and the target "
        "version is exact-pinned."
    )


def _validate_install_arguments(tokens: list[str]) -> None:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            # Bare positional, single-dash short option, or attached short value (-ihttps,
            # -f./dir): never legitimate build-mode input.
            raise SystemExit(_install_arguments_error(token))
        flag, sep, value = token.partition("=")
        if flag in _ALLOWED_INSTALL_BOOL_FLAGS:
            if sep:
                raise SystemExit(_install_arguments_error(token))
            index += 1
            continue
        if flag in _ALLOWED_INSTALL_VALUE_FLAGS:
            if sep:
                if not value:
                    raise SystemExit(_install_arguments_error(token))
                index += 1
                continue
            # Separate-token value form (e.g. --no-binary :all:): consume the next token
            # as the value so a bare package name can never slip through as a positional.
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("-"):
                raise SystemExit(_install_arguments_error(token))
            index += 2
            continue
        raise SystemExit(_install_arguments_error(token))


def _parse_timeout(raw: str) -> float:
    try:
        minutes = float(raw.strip())
    except ValueError:
        raise SystemExit(f"install-check-timeout-minutes must be a number: {raw!r}.") from None
    if minutes <= 0:
        raise SystemExit(f"install-check-timeout-minutes must be greater than zero: {raw!r}.")
    return minutes


# --- side-effecting helpers ------------------------------------------------- #


def _is_version_visible(url: str) -> bool:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return 200 <= response.status < 300
    except urllib.error.HTTPError as error:
        # 404 means "not published yet". Transient CDN / rate-limit responses (any
        # 5xx, plus 429) are ALSO treated as not-yet-visible so a blip does not crash
        # the whole install-check: the loop is deadline-bounded, so this cannot extend
        # polling past the timeout. Only non-transient client errors (e.g. 403) fail fast.
        if error.code == 404 or error.code == 429 or error.code >= 500:
            return False
        raise
    except urllib.error.URLError:
        return False


def _wait_for_version(index: str, name: str, version: str, deadline: float) -> None:
    url = version_json_url(index, name, version)
    while True:
        if _is_version_visible(url):
            return
        if time.monotonic() >= deadline:
            raise SystemExit(
                f"{name}=={version} did not become visible on {index} before the "
                "install-check timeout; the index may still be propagating."
            )
        print(f"waiting for {name}=={version} to appear on {index} ...")
        time.sleep(_POLL_INTERVAL_SECONDS)


def _create_venv(workdir: Path) -> str:
    import shutil

    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    venv_dir = workdir / ".venv"
    subprocess.run(["uv", "venv", str(venv_dir)], check=True)
    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(python)


def _install(index: str, name: str, version: str, extra_args: list[str], venv_python: str) -> None:
    command = build_install_command(index, name, version, extra_args, venv_python)
    print("running:", " ".join(shlex.quote(part) for part in command))
    subprocess.run(command, check=True)


def _import_check(venv_python: str, import_names: list[str]) -> None:
    if not import_names:
        print("no install-check-import-names given; install-only smoke check.")
        return
    for module in import_names:
        script = (
            "import importlib, sys;"
            "m = importlib.import_module(sys.argv[1]);"
            "print(sys.argv[1], getattr(m, '__version__', '(no __version__)'))"
        )
        subprocess.run([venv_python, "-c", script, module], check=True)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


if __name__ == "__main__":
    sys.exit(main())
