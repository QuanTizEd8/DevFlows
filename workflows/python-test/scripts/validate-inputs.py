from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, NoReturn

# Fail-fast validation for the python-test workflow. The matrix is the only
# structured input; it is parsed and schema-checked here, in a dedicated validate
# job, so a misconfigured call fails loudly BEFORE any leg schedules. The job
# re-emits the NORMALIZED matrix (derived unique leg names, resolved per-leg
# environment file, precomputed micromamba create-args) as a job output, which the
# test job consumes via fromJSON(needs.validate.outputs.matrix). All inputs arrive
# through environment variables; nothing is interpolated into a shell body.

ENV_MANAGERS = ("uv", "micromamba")
INSTALL_SOURCES = ("source", "artifact")
INSTALL_PREFERS = ("wheel", "sdist")
ALLOWED_LEG_KEYS = frozenset(
    {"runner", "python-version", "name", "environment-file", "test-arguments"}
)
NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"python-test: {message}")


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _as_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _parse_matrix(raw: str) -> list[dict[str, Any]]:
    stripped = raw.strip()
    if not stripped:
        _fail("test-matrix must be a non-empty JSON array of leg objects.")
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as error:
        _fail(f"test-matrix must be valid JSON: {error}.")
    if not isinstance(data, list):
        _fail("test-matrix must be a JSON array of leg objects.")
    if not data:
        _fail("test-matrix must not be empty; declare at least one leg.")
    for index, leg in enumerate(data):
        if not isinstance(leg, dict):
            _fail(f"test-matrix leg {index} must be an object; got {type(leg).__name__}.")
    return data


def _validated_runner(index: int, runner: Any) -> str | list[str]:
    if isinstance(runner, str):
        if not runner.strip():
            _fail(f"test-matrix leg {index} runner must not be empty.")
        return runner
    if isinstance(runner, list):
        if not runner or not all(isinstance(label, str) and label.strip() for label in runner):
            _fail(f"test-matrix leg {index} runner array must be non-empty strings.")
        return runner
    _fail(f"test-matrix leg {index} requires a runner (string or array of labels).")


def _resolved_name(
    index: int,
    given: Any,
    runner: str | list[str],
    python_version: str,
    seen_names: dict[str, int],
) -> str:
    if given is not None:
        if not isinstance(given, str) or not NAME_PATTERN.match(given):
            _fail(f"test-matrix leg {index} name must match {NAME_PATTERN.pattern}; got {given!r}.")
        name = given
    else:
        runner_label = runner if isinstance(runner, str) else "-".join(runner)
        base = f"{runner_label}-py{python_version}" if python_version else runner_label
        name = _SANITIZE.sub("-", base).strip("-")
        if not name:
            _fail(f"test-matrix leg {index} produced an empty derived name; set an explicit name.")
    if name in seen_names:
        _fail(
            f"test-matrix leg names must be unique; {name!r} is shared by legs "
            f"{seen_names[name]} and {index}. Set a distinct name."
        )
    seen_names[name] = index
    return name


def _normalize_leg(
    index: int,
    leg: dict[str, Any],
    env_manager: str,
    workflow_env_file: str,
    seen_names: dict[str, int],
) -> dict[str, Any]:
    unknown = set(leg) - ALLOWED_LEG_KEYS
    if unknown:
        _fail(
            f"test-matrix leg {index} has unknown keys {sorted(unknown)}; "
            f"allowed keys are {sorted(ALLOWED_LEG_KEYS)}."
        )

    runner = _validated_runner(index, leg.get("runner"))

    python_version = leg.get("python-version")
    if python_version is not None and not isinstance(python_version, str):
        _fail(f"test-matrix leg {index} python-version must be a string.")
    python_version = python_version or ""
    if env_manager == "uv" and not python_version:
        _fail(f"test-matrix leg {index} requires python-version for uv legs.")

    leg_env_file = leg.get("environment-file")
    if leg_env_file is not None and not isinstance(leg_env_file, str):
        _fail(f"test-matrix leg {index} environment-file must be a string.")
    if env_manager == "uv" and (leg_env_file or workflow_env_file.strip()):
        _fail(
            "environment files are not supported with test-env-manager uv; leg "
            f"{index} or test-environment-file set one."
        )

    resolved_env_file = ""
    create_args = ""
    if env_manager == "micromamba":
        candidate = leg_env_file if leg_env_file else workflow_env_file
        resolved_env_file = candidate.strip() if candidate else ""
        if not resolved_env_file:
            _fail(
                "test-env-manager micromamba requires an environment file: set "
                f"test-environment-file or environment-file on leg {index}."
            )
        create_args = f"python={python_version}" if python_version else ""

    test_arguments = leg.get("test-arguments", "")
    if not isinstance(test_arguments, str):
        _fail(f"test-matrix leg {index} test-arguments must be a string.")

    name = _resolved_name(index, leg.get("name"), runner, python_version, seen_names)

    normalized: dict[str, Any] = {
        "runner": runner,
        "name": name,
        "test-arguments": test_arguments,
    }
    if python_version:
        normalized["python-version"] = python_version
    if env_manager == "micromamba":
        normalized["environment-file"] = resolved_env_file
        normalized["create-args"] = create_args
    return normalized


def normalize(
    *,
    raw_matrix: str,
    env_manager: str,
    workflow_env_file: str,
    install_source: str,
    install_prefer: str,
    dependency_groups: str,
    report_enabled: bool,
    report_path: str,
) -> list[dict[str, Any]]:
    if env_manager not in ENV_MANAGERS:
        _fail(f"test-env-manager must be one of {list(ENV_MANAGERS)}; got {env_manager!r}.")
    if install_source not in INSTALL_SOURCES:
        _fail(
            f"test-install-source must be one of {list(INSTALL_SOURCES)}; got {install_source!r}."
        )
    if install_prefer not in INSTALL_PREFERS:
        _fail(
            f"test-install-prefer must be one of {list(INSTALL_PREFERS)}; got {install_prefer!r}."
        )
    if report_enabled and not report_path.strip():
        _fail("report-artifact-enabled requires a non-empty report-path.")
    if env_manager == "micromamba" and _split_lines(dependency_groups):
        _fail(
            "test-dependency-groups is not supported with test-env-manager micromamba; "
            "use test-dependencies or add the packages to the environment file."
        )

    legs = _parse_matrix(raw_matrix)
    seen_names: dict[str, int] = {}
    return [
        _normalize_leg(index, leg, env_manager, workflow_env_file, seen_names)
        for index, leg in enumerate(legs)
    ]


def main() -> int:
    normalized = normalize(
        raw_matrix=os.environ["TEST_MATRIX"],
        env_manager=os.environ.get("TEST_ENV_MANAGER", "uv"),
        workflow_env_file=os.environ.get("TEST_ENVIRONMENT_FILE", ""),
        install_source=os.environ.get("TEST_INSTALL_SOURCE", "source"),
        install_prefer=os.environ.get("TEST_INSTALL_PREFER", "wheel"),
        dependency_groups=os.environ.get("TEST_DEPENDENCY_GROUPS", ""),
        report_enabled=_as_bool(os.environ.get("REPORT_ARTIFACT_ENABLED", "false")),
        report_path=os.environ.get("REPORT_PATH", ""),
    )
    payload = json.dumps(normalized, separators=(",", ":"))
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"matrix={payload}\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
