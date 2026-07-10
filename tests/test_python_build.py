from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from devflows.catalog import load_workflow
from devflows.publish import build_published_workflow

SCRIPT_DIR = Path("workflows/python-build/scripts")


def _load_script(name: str) -> ModuleType:
    path = SCRIPT_DIR / name
    module_name = "python_build_" + name.replace("-", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses (collect.py) can resolve annotations via
    # sys.modules under `from __future__ import annotations`.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _parse_github_output(path: Path) -> dict[str, str]:
    """Parse a GITHUB_OUTPUT file written with the ``name<<DELIM`` heredoc form."""
    parsed: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if "<<" in line:
            name, _, delimiter = line.partition("<<")
            index += 1
            body: list[str] = []
            while index < len(lines) and lines[index] != delimiter:
                body.append(lines[index])
                index += 1
            parsed[name] = "\n".join(body)
        index += 1
    return parsed


# --------------------------------------------------------------------------- #
# validate-inputs.py                                                           #
# --------------------------------------------------------------------------- #
_VALIDATE_BASE = {
    "BUILD_TOOL": "uv",
    "BUILD_SDIST_ENABLED": "true",
    "BUILD_WHEEL_ENABLED": "true",
    "CIBW_ENABLED": "false",
    "CIBW_MATRIX": "[]",
    "CONDA_ENABLED": "false",
    "CONDA_RECIPE_PATH": "",
    "CONDA_MATRIX": '[{"runner": "ubuntu-latest"}]',
    "DIST_ARTIFACT_PREFIX": "python-build",
}


def _run_validate(monkeypatch, **overrides) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in {**_VALIDATE_BASE, **overrides}.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0


def _expect_validate_failure(monkeypatch, message: str, **overrides) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in {**_VALIDATE_BASE, **overrides}.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert message in str(excinfo.value)


def test_validate_accepts_pure_defaults(monkeypatch) -> None:
    _run_validate(monkeypatch)


def test_validate_accepts_cibw_only_leg(monkeypatch) -> None:
    _run_validate(
        monkeypatch,
        BUILD_SDIST_ENABLED="false",
        BUILD_WHEEL_ENABLED="false",
        CIBW_ENABLED="true",
        CIBW_MATRIX=json.dumps([{"runner": "ubuntu-latest", "only": "cp313-manylinux_x86_64"}]),
    )


def test_validate_accepts_cibw_build_and_archs(monkeypatch) -> None:
    _run_validate(
        monkeypatch,
        CIBW_ENABLED="true",
        CIBW_MATRIX=json.dumps(
            [{"runner": "ubuntu-latest", "build": "cp3*-*", "archs": "x86_64 aarch64"}]
        ),
    )


def test_validate_accepts_conda(monkeypatch) -> None:
    _run_validate(
        monkeypatch,
        BUILD_SDIST_ENABLED="false",
        BUILD_WHEEL_ENABLED="false",
        CONDA_ENABLED="true",
        CONDA_RECIPE_PATH="conda.recipe/recipe.yaml",
        CONDA_MATRIX=json.dumps([{"runner": "ubuntu-latest", "target-platform": "noarch"}]),
    )


def test_validate_rejects_unknown_build_tool(monkeypatch) -> None:
    _expect_validate_failure(monkeypatch, "build-tool must be", BUILD_TOOL="poetry")


def test_validate_rejects_nothing_to_build(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "Nothing to build",
        BUILD_SDIST_ENABLED="false",
        BUILD_WHEEL_ENABLED="false",
        CIBW_ENABLED="false",
        CONDA_ENABLED="false",
    )


def test_validate_rejects_cibw_enabled_empty_matrix(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "cibw-matrix is empty",
        CIBW_ENABLED="true",
        CIBW_MATRIX="[]",
    )


def test_validate_rejects_malformed_matrix_json(monkeypatch) -> None:
    _expect_validate_failure(monkeypatch, "not valid JSON", CIBW_MATRIX="{not json")


def test_validate_rejects_matrix_not_array(monkeypatch) -> None:
    _expect_validate_failure(monkeypatch, "must be a JSON array", CIBW_MATRIX='{"runner": "x"}')


def test_validate_rejects_cibw_leg_missing_runner(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "runner is required",
        CIBW_ENABLED="true",
        CIBW_MATRIX=json.dumps([{"only": "cp313-manylinux_x86_64"}]),
    )


def test_validate_rejects_cibw_only_and_build(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "mutually exclusive",
        CIBW_ENABLED="true",
        CIBW_MATRIX=json.dumps(
            [{"runner": "ubuntu-latest", "only": "cp313-manylinux_x86_64", "build": "cp3*"}]
        ),
    )


def test_validate_rejects_cibw_unknown_key(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "unsupported keys",
        CIBW_ENABLED="true",
        CIBW_MATRIX=json.dumps([{"runner": "ubuntu-latest", "platform": "linux"}]),
    )


def test_validate_rejects_cibw_injection_in_selector(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "unsupported characters",
        CIBW_ENABLED="true",
        CIBW_MATRIX=json.dumps([{"runner": "ubuntu-latest", "build": "cp3*\nEVIL=1"}]),
    )


def test_validate_rejects_conda_without_recipe(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "conda-recipe-path is empty",
        CONDA_ENABLED="true",
        CONDA_RECIPE_PATH="",
    )


def test_validate_rejects_conda_empty_matrix(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "conda-matrix is empty",
        CONDA_ENABLED="true",
        CONDA_RECIPE_PATH="conda.recipe/recipe.yaml",
        CONDA_MATRIX="[]",
    )


def test_validate_rejects_conda_bad_target_platform(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "not a valid conda platform",
        CONDA_ENABLED="true",
        CONDA_RECIPE_PATH="conda.recipe/recipe.yaml",
        CONDA_MATRIX=json.dumps([{"runner": "ubuntu-latest", "target-platform": "linux/64"}]),
    )


@pytest.mark.parametrize("prefix", ["", "has space", "bad/slash", "colon:name"])
def test_validate_rejects_unsafe_prefix(monkeypatch, prefix) -> None:
    message = "DIST_ARTIFACT_PREFIX is required" if prefix == "" else "artifact-name-safe"
    _expect_validate_failure(monkeypatch, message, DIST_ARTIFACT_PREFIX=prefix)


# --------------------------------------------------------------------------- #
# build-dist.py                                                                #
# --------------------------------------------------------------------------- #
def _pure_package(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    (workspace / "pkg").mkdir(parents=True)
    (workspace / "pkg" / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return workspace


def _fake_build(out_dir: Path, *, sdist: bool, wheel: bool):
    def runner(command, *, check):
        # Simulate the build tool writing the requested distribution kinds.
        if sdist:
            (out_dir / "python_build_fixture-0.1.0.tar.gz").write_bytes(b"sdist")
        if wheel:
            (out_dir / "python_build_fixture-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
        return subprocess.CompletedProcess(command, 0)

    return runner


def _run_build_dist(monkeypatch, tmp_path, *, recorded, **overrides) -> ModuleType:
    module = _load_script("build-dist.py")
    workspace = _pure_package(tmp_path)
    out_dir = tmp_path / "out"
    env = {
        "BUILD_TOOL": "uv",
        "BUILD_SDIST_ENABLED": "true",
        "BUILD_WHEEL_ENABLED": "true",
        "BUILD_TOOL_VERSION": "",
        "BUILD_TOOL_ARGUMENTS": "",
        "BUILD_PACKAGE_PATH": "pkg",
        "GITHUB_WORKSPACE": str(workspace),
        "OUT_DIR": str(out_dir),
        **overrides,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    out_dir.mkdir(parents=True, exist_ok=True)

    def runner(command, *, check):
        recorded.append(command)
        sdist = "--sdist" in command
        wheel = "--wheel" in command
        if command[:4] == ["python", "-m", "pip", "install"] or "pip" in command[:3]:
            return subprocess.CompletedProcess(command, 0)
        return _fake_build(out_dir, sdist=sdist, wheel=wheel)(command, check=check)

    monkeypatch.setattr(module.subprocess, "run", runner)
    return module


def test_build_dist_uv_builds_both(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_dist(monkeypatch, tmp_path, recorded=recorded)
    assert module.main() == 0
    command = recorded[0]
    assert command[:2] == ["uv", "build"]
    assert "--sdist" in command and "--wheel" in command
    assert "--out-dir" in command


def test_build_dist_uv_sdist_only(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_dist(monkeypatch, tmp_path, recorded=recorded, BUILD_WHEEL_ENABLED="false")
    assert module.main() == 0
    assert "--sdist" in recorded[0] and "--wheel" not in recorded[0]


def test_build_dist_passes_extra_arguments(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_dist(
        monkeypatch, tmp_path, recorded=recorded, BUILD_TOOL_ARGUMENTS="--no-build-isolation"
    )
    assert module.main() == 0
    assert "--no-build-isolation" in recorded[0]


def test_build_dist_python_build_installs_frontend(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_dist(
        monkeypatch,
        tmp_path,
        recorded=recorded,
        BUILD_TOOL="python-build",
        BUILD_TOOL_VERSION="1.2.1",
    )
    assert module.main() == 0
    assert any(cmd[:4] == [module.sys.executable, "-m", "pip", "install"] for cmd in recorded)
    assert any("build==1.2.1" in cmd for cmd in recorded)
    build_cmd = [cmd for cmd in recorded if "-m" in cmd and "build" in cmd and "--outdir" in cmd][0]
    assert "--outdir" in build_cmd


def test_build_dist_rejects_path_outside_workspace(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_dist(
        monkeypatch, tmp_path, recorded=recorded, BUILD_PACKAGE_PATH="../escape"
    )
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "GITHUB_WORKSPACE" in str(excinfo.value)


def test_build_dist_rejects_missing_pyproject(monkeypatch, tmp_path) -> None:
    module = _load_script("build-dist.py")
    workspace = tmp_path / "ws"
    (workspace / "empty").mkdir(parents=True)
    for key, value in {
        "BUILD_TOOL": "uv",
        "BUILD_SDIST_ENABLED": "true",
        "BUILD_WHEEL_ENABLED": "true",
        "BUILD_PACKAGE_PATH": "empty",
        "GITHUB_WORKSPACE": str(workspace),
        "OUT_DIR": str(tmp_path / "out"),
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "pyproject.toml" in str(excinfo.value)


def test_build_dist_fails_when_expected_output_missing(monkeypatch, tmp_path) -> None:
    module = _load_script("build-dist.py")
    workspace = _pure_package(tmp_path)
    out_dir = tmp_path / "out"
    for key, value in {
        "BUILD_TOOL": "uv",
        "BUILD_SDIST_ENABLED": "true",
        "BUILD_WHEEL_ENABLED": "false",
        "BUILD_PACKAGE_PATH": "pkg",
        "GITHUB_WORKSPACE": str(workspace),
        "OUT_DIR": str(out_dir),
    }.items():
        monkeypatch.setenv(key, value)
    # A build that exits 0 but produces nothing must fail the job.
    monkeypatch.setattr(
        module.subprocess, "run", lambda command, *, check: subprocess.CompletedProcess(command, 0)
    )
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "no sdist" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# prepare-cibw-env.py                                                          #
# --------------------------------------------------------------------------- #
def _run_prepare_cibw(monkeypatch, tmp_path, **env) -> Path:
    module = _load_script("prepare-cibw-env.py")
    github_env = tmp_path / "github-env"
    github_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    return github_env


def test_prepare_cibw_exports_build_and_archs(monkeypatch, tmp_path) -> None:
    github_env = _run_prepare_cibw(
        monkeypatch, tmp_path, MATRIX_BUILD="cp313-*", MATRIX_ARCHS="x86_64 aarch64"
    )
    content = github_env.read_text(encoding="utf-8")
    assert "CIBW_BUILD=cp313-*" in content
    assert "CIBW_ARCHS=x86_64 aarch64" in content


def test_prepare_cibw_skips_empty_values(monkeypatch, tmp_path) -> None:
    github_env = _run_prepare_cibw(monkeypatch, tmp_path, MATRIX_BUILD="", MATRIX_ARCHS="")
    assert github_env.read_text(encoding="utf-8") == ""


def test_prepare_cibw_rejects_injection(monkeypatch, tmp_path) -> None:
    module = _load_script("prepare-cibw-env.py")
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "github-env"))
    monkeypatch.setenv("MATRIX_BUILD", "cp313\nSECRET=leak")
    monkeypatch.setenv("MATRIX_ARCHS", "")
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "unsupported characters" in str(excinfo.value)


def test_prepare_cibw_requires_github_env(monkeypatch) -> None:
    module = _load_script("prepare-cibw-env.py")
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    monkeypatch.setenv("MATRIX_BUILD", "cp313-*")
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "GITHUB_ENV" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# build-conda.py                                                               #
# --------------------------------------------------------------------------- #
def _conda_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    (workspace / "conda.recipe").mkdir(parents=True)
    (workspace / "conda.recipe" / "recipe.yaml").write_text("package:\n", encoding="utf-8")
    return workspace


def _run_build_conda(monkeypatch, tmp_path, *, recorded, produce=True, **overrides) -> ModuleType:
    module = _load_script("build-conda.py")
    workspace = _conda_workspace(tmp_path)
    out_dir = tmp_path / "out"
    env = {
        "GITHUB_WORKSPACE": str(workspace),
        "CONDA_RECIPE_PATH": "conda.recipe/recipe.yaml",
        "CONDA_CHANNELS": "conda-forge\nbioconda",
        "CONDA_BUILD_ARGUMENTS": "",
        "MATRIX_TARGET_PLATFORM": "",
        "OUT_DIR": str(out_dir),
        **overrides,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def runner(command, *, check):
        recorded.append(command)
        if produce:
            subdir = out_dir / "noarch"
            subdir.mkdir(parents=True, exist_ok=True)
            (subdir / "python-build-conda-fixture-0.1.0-0.conda").write_bytes(b"pkg")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", runner)
    return module


def test_build_conda_builds_with_channels(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_conda(monkeypatch, tmp_path, recorded=recorded)
    assert module.main() == 0
    command = recorded[0]
    assert command[:2] == ["rattler-build", "build"]
    assert command.count("-c") == 2
    assert "conda-forge" in command and "bioconda" in command
    assert "--target-platform" not in command


def test_build_conda_includes_target_platform(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_conda(
        monkeypatch, tmp_path, recorded=recorded, MATRIX_TARGET_PLATFORM="linux-64"
    )
    assert module.main() == 0
    assert "--target-platform" in recorded[0]
    assert "linux-64" in recorded[0]


def test_build_conda_rejects_recipe_outside_workspace(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_conda(
        monkeypatch, tmp_path, recorded=recorded, CONDA_RECIPE_PATH="../escape/recipe.yaml"
    )
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "GITHUB_WORKSPACE" in str(excinfo.value)


def test_build_conda_fails_when_no_packages(monkeypatch, tmp_path) -> None:
    recorded: list[list[str]] = []
    module = _run_build_conda(monkeypatch, tmp_path, recorded=recorded, produce=False)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "no conda packages" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# collect.py                                                                   #
# --------------------------------------------------------------------------- #
def _make_wheel(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(name.encode("utf-8"))


def _collect_env(tmp_path: Path, **overrides) -> dict[str, str]:
    root = tmp_path
    env = {
        "DIST_ARTIFACT_PREFIX": "python-build",
        "DIST_STAGING": str(root / "in/dist"),
        "CIBW_STAGING": str(root / "in/cibw"),
        "CONDA_STAGING": str(root / "in/conda"),
        "SDIST_OUT": str(root / "out/sdist"),
        "WHEELS_OUT": str(root / "out/wheels"),
        "CONDA_OUT": str(root / "out/conda-channel"),
        "GITHUB_OUTPUT": str(root / "github-output"),
        "GITHUB_STEP_SUMMARY": str(root / "step-summary"),
    }
    env.update(overrides)
    return env


def _run_collect(monkeypatch, env: dict[str, str], *, reindex_calls: list) -> ModuleType:
    module = _load_script("collect.py")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    Path(env["GITHUB_OUTPUT"]).write_text("", encoding="utf-8")

    def runner(command, *, check):
        reindex_calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", runner)
    return module


def test_collect_aggregates_sdist_and_wheels(monkeypatch, tmp_path) -> None:
    env = _collect_env(tmp_path)
    _make_wheel(Path(env["DIST_STAGING"]), "python_build_fixture-0.1.0-py3-none-any.whl")
    Path(env["DIST_STAGING"], "python_build_fixture-0.1.0.tar.gz").write_bytes(b"sdist")
    reindex: list = []
    module = _run_collect(monkeypatch, env, reindex_calls=reindex)
    assert module.main() == 0
    outputs = _parse_github_output(Path(env["GITHUB_OUTPUT"]))
    assert outputs["package-version"] == "0.1.0"
    assert outputs["sdist-artifact-name"] == "python-build-sdist"
    assert outputs["wheels-artifact-name"] == "python-build-wheels"
    assert outputs["conda-artifact-name"] == ""
    # No conda packages, so the indexer must not run.
    assert reindex == []
    # Wheelhouse and sdist directories hold the copied files flat.
    assert (Path(env["WHEELS_OUT"]) / "python_build_fixture-0.1.0-py3-none-any.whl").is_file()
    assert (Path(env["SDIST_OUT"]) / "python_build_fixture-0.1.0.tar.gz").is_file()


def test_collect_merges_wheels_from_dist_and_cibw(monkeypatch, tmp_path) -> None:
    env = _collect_env(tmp_path)
    _make_wheel(Path(env["DIST_STAGING"]), "pkg-0.1.0-py3-none-any.whl")
    _make_wheel(Path(env["CIBW_STAGING"]) / "leg0", "pkg-0.1.0-cp313-cp313-manylinux_x86_64.whl")
    _make_wheel(Path(env["CIBW_STAGING"]) / "leg1", "pkg-0.1.0-cp313-cp313-macosx_arm64.whl")
    reindex: list = []
    module = _run_collect(monkeypatch, env, reindex_calls=reindex)
    assert module.main() == 0
    wheels = sorted(p.name for p in Path(env["WHEELS_OUT"]).glob("*.whl"))
    assert len(wheels) == 3
    outputs = _parse_github_output(Path(env["GITHUB_OUTPUT"]))
    assert outputs["package-version"] == "0.1.0"


def test_collect_manifest_and_digests(monkeypatch, tmp_path) -> None:
    env = _collect_env(tmp_path)
    _make_wheel(Path(env["DIST_STAGING"]), "pkg-0.1.0-py3-none-any.whl")
    reindex: list = []
    module = _run_collect(monkeypatch, env, reindex_calls=reindex)
    assert module.main() == 0
    outputs = _parse_github_output(Path(env["GITHUB_OUTPUT"]))
    manifest = json.loads(outputs["dist-manifest"])
    assert manifest["schema"] == 1
    assert manifest["artifacts"] == {
        "sdist": "",
        "wheels": "python-build-wheels",
        "conda-channel": "",
    }
    entry = manifest["files"][0]
    assert entry["kind"] == "wheel"
    assert entry["name"] == "pkg-0.1.0-py3-none-any.whl"
    assert len(entry["sha256"]) == 64
    assert entry["size"] == len(b"pkg-0.1.0-py3-none-any.whl")
    # dist-sha256sums decodes to sha256sum-format lines.
    decoded = base64.b64decode(outputs["dist-sha256sums"]).decode("utf-8")
    assert decoded == f"{entry['sha256']}  pkg-0.1.0-py3-none-any.whl\n"


def test_collect_conda_channel_reindexed(monkeypatch, tmp_path) -> None:
    env = _collect_env(tmp_path)
    conda_leg = Path(env["CONDA_STAGING"]) / "noarch"
    conda_leg.mkdir(parents=True)
    (conda_leg / "python-build-conda-fixture-0.1.0-0.conda").write_bytes(b"conda")
    reindex: list = []
    module = _run_collect(monkeypatch, env, reindex_calls=reindex)
    assert module.main() == 0
    outputs = _parse_github_output(Path(env["GITHUB_OUTPUT"]))
    assert outputs["conda-artifact-name"] == "python-build-conda-channel"
    assert outputs["package-version"] == "0.1.0"
    # The channel preserves the subdir and the indexer ran against the channel root.
    channel_pkg = Path(env["CONDA_OUT"]) / "noarch" / "python-build-conda-fixture-0.1.0-0.conda"
    assert channel_pkg.is_file()
    assert len(reindex) == 1
    assert reindex[0][:2] == ["uv", "run"]
    assert f"conda-index=={module.CONDA_INDEX_VERSION}" in reindex[0]
    assert reindex[0][-1] == str(Path(env["CONDA_OUT"]).resolve())


def test_collect_rejects_version_mismatch(monkeypatch, tmp_path) -> None:
    env = _collect_env(tmp_path)
    _make_wheel(Path(env["DIST_STAGING"]), "pkg-0.1.0-py3-none-any.whl")
    _make_wheel(Path(env["CIBW_STAGING"]), "pkg-0.2.0-cp313-cp313-manylinux_2_28_x86_64.whl")
    reindex: list = []
    module = _run_collect(monkeypatch, env, reindex_calls=reindex)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "disagree on version" in str(excinfo.value)


def test_collect_rejects_duplicate_wheel(monkeypatch, tmp_path) -> None:
    env = _collect_env(tmp_path)
    _make_wheel(Path(env["DIST_STAGING"]), "pkg-0.1.0-py3-none-any.whl")
    _make_wheel(Path(env["CIBW_STAGING"]), "pkg-0.1.0-py3-none-any.whl")
    reindex: list = []
    module = _run_collect(monkeypatch, env, reindex_calls=reindex)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "duplicate distribution file" in str(excinfo.value)


def test_collect_fails_when_nothing_aggregated(monkeypatch, tmp_path) -> None:
    env = _collect_env(tmp_path)
    reindex: list = []
    module = _run_collect(monkeypatch, env, reindex_calls=reindex)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "no distribution files" in str(excinfo.value)


@pytest.mark.parametrize(
    ("filename", "kind", "expected"),
    [
        ("pkg-0.1.0-py3-none-any.whl", "wheel", "0.1.0"),
        ("my_pkg-1.2.3.tar.gz", "sdist", "1.2.3"),
        ("python-build-conda-fixture-0.1.0-0.conda", "conda", "0.1.0"),
        ("some-pkg-2.0.0-h123_0.tar.bz2", "conda", "2.0.0"),
    ],
)
def test_collect_version_parsing(filename, kind, expected) -> None:
    module = _load_script("collect.py")
    assert module._parse_version(filename, kind) == expected


def test_collect_writes_step_summary(monkeypatch, tmp_path) -> None:
    env = _collect_env(tmp_path)
    _make_wheel(Path(env["DIST_STAGING"]), "pkg-0.1.0-py3-none-any.whl")
    reindex: list = []
    module = _run_collect(monkeypatch, env, reindex_calls=reindex)
    assert module.main() == 0
    summary = Path(env["GITHUB_STEP_SUMMARY"]).read_text(encoding="utf-8")
    assert "python-build distribution manifest" in summary
    assert "pkg-0.1.0-py3-none-any.whl" in summary


# --------------------------------------------------------------------------- #
# generated interface snapshot                                                 #
# --------------------------------------------------------------------------- #
def _published():
    return build_published_workflow(load_workflow(Path("workflows/python-build")))


def test_interface_inputs_match_design() -> None:
    published = _published()
    inputs = set(published["on"]["workflow_call"]["inputs"])
    workflow_specific = {
        "build-package-path",
        "build-tool",
        "build-tool-version",
        "build-python-version",
        "build-sdist-enabled",
        "build-wheel-enabled",
        "build-tool-arguments",
        "build-runner",
        "build-timeout-minutes",
        "cibw-enabled",
        "cibw-matrix",
        "cibw-config-file",
        "cibw-fail-fast",
        "cibw-timeout-minutes",
        "conda-enabled",
        "conda-recipe-path",
        "conda-matrix",
        "conda-channels",
        "conda-build-arguments",
        "conda-fail-fast",
        "conda-timeout-minutes",
        "dist-artifact-prefix",
        "dist-artifact-retention-days",
    }
    assert workflow_specific <= inputs
    # Generator injects the checkout + artifact-download channel inputs.
    assert {"checkout-enabled", "artifact-download-enabled"} <= inputs
    # artifact-upload and writeback channels are intentionally NOT declared.
    assert "artifact-upload-enabled" not in inputs
    assert "commit-enabled" not in inputs


def test_interface_outputs_match_design() -> None:
    published = _published()
    outputs = set(published["on"]["workflow_call"]["outputs"])
    assert outputs == {
        "sdist-artifact-name",
        "wheels-artifact-name",
        "conda-artifact-name",
        "dist-sha256sums",
        "dist-manifest",
        "package-version",
    }


def test_interface_permissions_are_least_privilege() -> None:
    published = _published()
    assert published["permissions"] == {"contents": "read"}
    jobs = published["jobs"]
    # dist hosts the artifact-download channel, so it is granted actions: read.
    assert jobs["dist"]["permissions"] == {"contents": "read", "actions": "read"}
    # collect downloads the run-internal intermediates via explicit pinned steps.
    assert jobs["collect"]["permissions"] == {"contents": "read", "actions": "read"}
    # validate / cibw / conda inherit the workflow-level contents: read only.
    for job_id in ("validate", "cibw", "conda"):
        assert "permissions" not in jobs[job_id]


def test_collect_gate_expression_is_explicit() -> None:
    gate = _published()["jobs"]["collect"]["if"]
    assert "!cancelled()" in gate
    # Every producer must be success-or-skipped (a failed enabled producer skips collect).
    for producer in ("dist", "cibw", "conda"):
        clause = f"needs.{producer}.result == 'success' || needs.{producer}.result == 'skipped'"
        assert clause in gate
    # And at least one producer must have succeeded.
    assert (
        "needs.dist.result == 'success' || needs.cibw.result == 'success' "
        "|| needs.conda.result == 'success'" in gate
    )


def test_matrix_jobs_receive_checkout_and_runtime() -> None:
    jobs = _published()["jobs"]
    for job_id in ("cibw", "conda"):
        step_names = [step.get("name") for step in jobs[job_id]["steps"]]
        assert "Checkout repository" in step_names
        assert "Materialize DevFlows runtime scripts" in step_names
    # collect materializes scripts but is not a checkout job.
    collect_names = [step.get("name") for step in jobs["collect"]["steps"]]
    assert "Materialize DevFlows runtime scripts" in collect_names
    assert "Checkout repository" not in collect_names
