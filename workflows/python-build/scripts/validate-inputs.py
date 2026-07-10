from __future__ import annotations

import json
import os
import re

# Build identifiers and architecture selectors reach cibuildwheel only through
# with:/env:, never a run: body, but the values are also written to $GITHUB_ENV
# by prepare-cibw-env.py, so they must not smuggle newlines or shell/`name=value`
# breakers. This grammar is deliberately narrow: cibuildwheel build selectors and
# CIBW_ARCHS use letters, digits, underscore, dot, hyphen, the glob metacharacters
# `*`/`?`, and spaces (arch lists such as "x86_64 aarch64").
_CIBW_SELECTOR = re.compile(r"^[A-Za-z0-9_.*?\- ]+$")
# conda subdir / target platform grammar: noarch, linux-64, osx-arm64, win-64, ...
_CONDA_PLATFORM = re.compile(r"^[A-Za-z0-9_-]+$")
# GitHub artifact names forbid " : < > | * ? \r \n \ / and control characters;
# the prefix also seeds run-internal names, so keep it to a conservative safe set.
_ARTIFACT_PREFIX = re.compile(r"^[A-Za-z0-9._-]+$")

_CIBW_LEG_KEYS = {"runner", "only", "build", "archs"}
_CONDA_LEG_KEYS = {"runner", "target-platform"}


def main() -> int:
    build_tool = _required("BUILD_TOOL")
    if build_tool not in {"uv", "python-build"}:
        raise SystemExit(f"build-tool must be 'uv' or 'python-build', got {build_tool!r}.")

    prefix = _required("DIST_ARTIFACT_PREFIX")
    if not _ARTIFACT_PREFIX.match(prefix):
        raise SystemExit(
            "dist-artifact-prefix must be a non-empty artifact-name-safe string "
            "(letters, digits, '.', '_', '-'); got "
            f"{prefix!r}."
        )

    build_sdist = _bool("BUILD_SDIST_ENABLED")
    build_wheel = _bool("BUILD_WHEEL_ENABLED")
    cibw_enabled = _bool("CIBW_ENABLED")
    conda_enabled = _bool("CONDA_ENABLED")

    cibw_matrix = _parse_matrix("CIBW_MATRIX", "cibw-matrix")
    _validate_cibw_matrix(cibw_matrix)
    if cibw_enabled and not cibw_matrix:
        raise SystemExit(
            "cibw-enabled is true but cibw-matrix is empty; supply at least one "
            "cibuildwheel leg or disable cibw-enabled."
        )

    conda_matrix = _parse_matrix("CONDA_MATRIX", "conda-matrix")
    _validate_conda_matrix(conda_matrix)
    if conda_enabled:
        if not os.environ.get("CONDA_RECIPE_PATH", "").strip():
            raise SystemExit(
                "conda-enabled is true but conda-recipe-path is empty; point it at "
                "a recipe.yaml (v1 recipe format)."
            )
        if not conda_matrix:
            raise SystemExit(
                "conda-enabled is true but conda-matrix is empty; supply at least "
                "one conda leg or disable conda-enabled."
            )

    if not (build_sdist or build_wheel or cibw_enabled or conda_enabled):
        raise SystemExit(
            "Nothing to build: enable at least one of build-sdist-enabled, "
            "build-wheel-enabled, cibw-enabled, or conda-enabled. This workflow "
            "never silently no-ops."
        )
    return 0


def _validate_cibw_matrix(matrix: list[object]) -> None:
    for index, leg in enumerate(matrix):
        where = f"cibw-matrix[{index}]"
        _require_object(leg, where)
        assert isinstance(leg, dict)
        _reject_unknown_keys(leg, _CIBW_LEG_KEYS, where)
        _require_runner(leg, where)
        only = _optional_string(leg, "only", where)
        build = _optional_string(leg, "build", where)
        archs = _optional_string(leg, "archs", where)
        if only and build:
            raise SystemExit(
                f"{where}: 'only' and 'build' are mutually exclusive; set at most one."
            )
        for field, value in (("only", only), ("build", build), ("archs", archs)):
            if value and not _CIBW_SELECTOR.match(value):
                raise SystemExit(
                    f"{where}.{field} contains unsupported characters: {value!r}. "
                    "Allowed: letters, digits, '_', '.', '-', '*', '?', and spaces."
                )


def _validate_conda_matrix(matrix: list[object]) -> None:
    for index, leg in enumerate(matrix):
        where = f"conda-matrix[{index}]"
        _require_object(leg, where)
        assert isinstance(leg, dict)
        _reject_unknown_keys(leg, _CONDA_LEG_KEYS, where)
        _require_runner(leg, where)
        target_platform = _optional_string(leg, "target-platform", where)
        if target_platform and not _CONDA_PLATFORM.match(target_platform):
            raise SystemExit(
                f"{where}.target-platform is not a valid conda platform: "
                f"{target_platform!r} (e.g. noarch, linux-64, osx-arm64)."
            )


def _parse_matrix(env_name: str, input_name: str) -> list[object]:
    raw = os.environ.get(env_name, "").strip() or "[]"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"{input_name} is not valid JSON: {error}.") from error
    if not isinstance(value, list):
        raise SystemExit(f"{input_name} must be a JSON array of leg objects.")
    return value


def _require_object(leg: object, where: str) -> None:
    if not isinstance(leg, dict):
        raise SystemExit(f"{where} must be a JSON object.")


def _reject_unknown_keys(leg: dict[object, object], allowed: set[str], where: str) -> None:
    unknown = sorted(str(key) for key in leg if str(key) not in allowed)
    if unknown:
        raise SystemExit(
            f"{where} has unsupported keys {unknown}; allowed keys are {sorted(allowed)}."
        )


def _require_runner(leg: dict[object, object], where: str) -> None:
    runner = leg.get("runner")
    if not isinstance(runner, str) or not runner.strip():
        raise SystemExit(f"{where}.runner is required and must be a non-empty string.")


def _optional_string(leg: dict[object, object], field: str, where: str) -> str:
    if field not in leg:
        return ""
    value = leg[field]
    if not isinstance(value, str):
        raise SystemExit(f"{where}.{field} must be a string when present.")
    return value.strip()


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
