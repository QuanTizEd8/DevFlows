from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


def main() -> int:
    recipe = _resolve_recipe_path()
    out_dir = Path(os.environ["OUT_DIR"]).resolve()
    target_platform = os.environ.get("MATRIX_TARGET_PLATFORM", "").strip()

    channels: list[str] = []
    for line in os.environ.get("CONDA_CHANNELS", "").splitlines():
        channel = line.strip()
        if channel:
            channels.append(channel)

    try:
        extra_args = shlex.split(os.environ.get("CONDA_BUILD_ARGUMENTS", ""))
    except ValueError as error:
        raise SystemExit(f"Unable to parse conda-build-arguments: {error}") from error

    out_dir.mkdir(parents=True, exist_ok=True)
    command = ["rattler-build", "build", "--recipe", str(recipe), "--output-dir", str(out_dir)]
    for channel in channels:
        command += ["-c", channel]
    if target_platform:
        command += ["--target-platform", target_platform]
    command += extra_args

    subprocess.run(command, check=True)
    _assert_built_packages(out_dir)
    return 0


def _resolve_recipe_path() -> Path:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    relative = os.environ.get("CONDA_RECIPE_PATH", "").strip()
    if not relative:
        raise SystemExit("conda-recipe-path is required.")
    recipe = (workspace / relative).resolve()
    if workspace != recipe and workspace not in recipe.parents:
        raise SystemExit("conda-recipe-path must stay inside GITHUB_WORKSPACE.")
    if not recipe.is_file():
        raise SystemExit(f"conda-recipe-path does not exist: {relative}")
    return recipe


def _assert_built_packages(out_dir: Path) -> None:
    packages = list(out_dir.rglob("*.conda")) + list(out_dir.rglob("*.tar.bz2"))
    if not packages:
        raise SystemExit(
            f"rattler-build produced no conda packages (*.conda / *.tar.bz2) in {out_dir}."
        )


if __name__ == "__main__":
    raise SystemExit(main())
