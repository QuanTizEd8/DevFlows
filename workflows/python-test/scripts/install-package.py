from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

# Installs the package under test into the leg's prepared environment. Everything
# is driven by environment variables and executed with argv lists (shell=False),
# so no caller string is ever interpolated into a shell body.
#
#   source   mode: install test-source-directory (with extras) from the checkout.
#   artifact mode: resolve the project name from the distributions in
#                  test-dist-path and install it with `--no-index --find-links`,
#                  so the resolver picks the compatible wheel from a multi-wheel
#                  wheelhouse (python-build's flat wheelhouse artifact). Zero
#                  distributions is a hard error - a broken chain never silently
#                  tests nothing.
#
# uv legs run `uv pip install` against the activated venv; micromamba legs run
# `python -m pip install` inside the activated conda environment. PEP 735
# dependency groups are uv-only (rejected for micromamba in validate).

_SDIST_SUFFIX = ".tar.gz"
_SDIST_NAME = re.compile(r"^(?P<name>.+?)-[0-9].*$")


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"python-test: {message}")


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _run(argv: list[str], *, cwd: str | None = None) -> None:
    printable = " ".join(shlex.quote(part) for part in argv)
    print(f"+ {printable}" + (f"  (cwd={cwd})" if cwd else ""), flush=True)
    completed = subprocess.run(argv, cwd=cwd)  # noqa: PLW1510 - explicit returncode handling
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _normalize_name(raw: str) -> str:
    return re.sub(r"[-_.]+", "-", raw).lower()


def _project_name(path: Path) -> str:
    filename = path.name
    if filename.endswith(".whl"):
        return _normalize_name(filename.split("-")[0])
    stem = filename[: -len(_SDIST_SUFFIX)]
    match = _SDIST_NAME.match(stem)
    return _normalize_name(match.group("name") if match else stem)


def _with_extras(base: str, extras: list[str]) -> str:
    return f"{base}[{','.join(extras)}]" if extras else base


def _installer(env_manager: str) -> list[str]:
    if env_manager == "uv":
        return ["uv", "pip", "install"]
    return ["python", "-m", "pip", "install"]


def _install_source(installer: list[str], source_directory: str, extras: list[str]) -> None:
    directory = Path(source_directory)
    if not directory.is_dir():
        _fail(f"test-source-directory does not exist: {source_directory}")
    target = _with_extras(str(directory.resolve()), extras)
    _run([*installer, target])


def _install_artifact(
    installer: list[str],
    dist_path: str,
    prefer: str,
    extras: list[str],
) -> None:
    directory = Path(dist_path)
    if not directory.is_dir():
        _fail(
            f"test-dist-path {dist_path!r} is not a directory; artifact install found no "
            "distributions (is the artifact-download chain configured to this path?)."
        )
    dist_files = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and (path.name.endswith(".whl") or path.name.endswith(_SDIST_SUFFIX))
    )
    if not dist_files:
        _fail(
            f"test-dist-path {dist_path!r} contains no wheels or sdists; artifact install "
            "found nothing to test."
        )
    names = sorted({_project_name(path) for path in dist_files})
    if len(names) > 1:
        _fail(
            f"test-dist-path {dist_path!r} contains multiple package names {names}; expected "
            "exactly one project's distributions."
        )
    find_links: list[str] = []
    for parent in sorted({str(path.parent) for path in dist_files}):
        find_links += ["--find-links", parent]
    only_flags = ["--no-binary", names[0]] if prefer == "sdist" else []
    spec = _with_extras(names[0], extras)
    _run([*installer, "--no-index", *find_links, *only_flags, spec])


def _install_dependency_groups(source_directory: str, groups: list[str]) -> None:
    directory = Path(source_directory)
    if not directory.is_dir():
        _fail(
            "test-dependency-groups needs the source tree's pyproject.toml, but "
            f"test-source-directory does not exist: {source_directory}"
        )
    group_flags: list[str] = []
    for group in groups:
        group_flags += ["--group", group]
    _run(["uv", "pip", "install", *group_flags], cwd=str(directory))


def main() -> int:
    env_manager = os.environ.get("TEST_ENV_MANAGER", "uv")
    install_source = os.environ.get("TEST_INSTALL_SOURCE", "source")
    source_directory = os.environ.get("TEST_SOURCE_DIRECTORY", ".") or "."
    dist_path = os.environ.get("TEST_DIST_PATH", "dist") or "dist"
    prefer = os.environ.get("TEST_INSTALL_PREFER", "wheel")
    extras = _split_lines(os.environ.get("TEST_INSTALL_EXTRAS", ""))
    groups = _split_lines(os.environ.get("TEST_DEPENDENCY_GROUPS", ""))
    dependencies = _split_lines(os.environ.get("TEST_DEPENDENCIES", ""))

    installer = _installer(env_manager)

    if install_source == "source":
        _install_source(installer, source_directory, extras)
    else:
        _install_artifact(installer, dist_path, prefer, extras)

    if groups:
        # Dependency groups are uv-only (validate rejects them for micromamba).
        _install_dependency_groups(source_directory, groups)

    if dependencies:
        _run([*installer, *dependencies])

    return 0


if __name__ == "__main__":
    sys.exit(main())
