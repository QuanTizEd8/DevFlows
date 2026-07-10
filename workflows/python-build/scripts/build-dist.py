from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


def main() -> int:
    build_tool = os.environ["BUILD_TOOL"].strip()
    build_sdist = _bool("BUILD_SDIST_ENABLED")
    build_wheel = _bool("BUILD_WHEEL_ENABLED")
    tool_version = os.environ.get("BUILD_TOOL_VERSION", "").strip()
    out_dir = Path(os.environ["OUT_DIR"]).resolve()
    package_dir = _resolve_package_dir()

    if not (build_sdist or build_wheel):
        # The dist job is guarded by `if: build-sdist-enabled || build-wheel-enabled`,
        # so reaching here with neither means a misconfiguration; fail loudly.
        raise SystemExit(
            "build-dist invoked with both build-sdist-enabled and build-wheel-enabled "
            "false; nothing to build."
        )

    try:
        extra_args = shlex.split(os.environ.get("BUILD_TOOL_ARGUMENTS", ""))
    except ValueError as error:
        raise SystemExit(f"Unable to parse build-tool-arguments: {error}") from error

    out_dir.mkdir(parents=True, exist_ok=True)
    flags: list[str] = []
    if build_sdist:
        flags.append("--sdist")
    if build_wheel:
        flags.append("--wheel")

    if build_tool == "uv":
        command = ["uv", "build", "--out-dir", str(out_dir), *flags, *extra_args, str(package_dir)]
    elif build_tool == "python-build":
        _install_build_frontend(tool_version)
        command = [
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(out_dir),
            *flags,
            *extra_args,
            str(package_dir),
        ]
    else:
        raise SystemExit(f"Unsupported build-tool {build_tool!r}.")

    subprocess.run(command, check=True)
    _assert_expected_outputs(out_dir, build_sdist=build_sdist, build_wheel=build_wheel)
    return 0


def _install_build_frontend(tool_version: str) -> None:
    """Install the PyPA ``build`` frontend into the setup-python environment."""
    spec = f"build=={tool_version}" if tool_version else "build"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", spec],
        check=True,
    )


def _resolve_package_dir() -> Path:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    relative = os.environ.get("BUILD_PACKAGE_PATH", ".").strip() or "."
    package_dir = (workspace / relative).resolve()
    if workspace != package_dir and workspace not in package_dir.parents:
        raise SystemExit("build-package-path must stay inside GITHUB_WORKSPACE.")
    if not package_dir.is_dir():
        raise SystemExit(f"build-package-path does not exist: {relative}")
    if not (package_dir / "pyproject.toml").is_file():
        raise SystemExit(f"build-package-path has no pyproject.toml: {relative}")
    return package_dir


def _assert_expected_outputs(out_dir: Path, *, build_sdist: bool, build_wheel: bool) -> None:
    """A build tool can exit 0 yet produce nothing the caller expected.

    Verify the requested distribution kinds actually landed so a misconfigured
    call fails here instead of silently uploading an empty intermediate.
    """
    if build_sdist and not list(out_dir.glob("*.tar.gz")):
        raise SystemExit(
            f"build-sdist-enabled is true but no sdist (*.tar.gz) was produced in {out_dir}."
        )
    if build_wheel and not list(out_dir.glob("*.whl")):
        raise SystemExit(
            f"build-wheel-enabled is true but no wheel (*.whl) was produced in {out_dir}."
        )


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
