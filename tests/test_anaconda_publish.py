from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from devflows.catalog import load_workflow
from devflows.publish import build_published_workflow, caller_required_permissions

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO / "workflows" / "anaconda-publish" / "scripts"

# The workflow scripts import their sibling ``specs.py`` (materialized next to them
# at run time); make that importable here too.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import specs  # type: ignore  # noqa: E402


def _load_script(name: str) -> ModuleType:
    path = SCRIPT_DIR / name
    module_name = "anaconda_publish_" + name.replace("-", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _parse_github_output(path: Path) -> dict[str, str]:
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
# specs.py: filename and spec parsing                                          #
# --------------------------------------------------------------------------- #
def test_parse_conda_filename_handles_hyphenated_names() -> None:
    assert specs.parse_conda_filename("my-pkg-1.2.3-h0_0.conda") == ("my-pkg", "1.2.3")
    assert specs.parse_conda_filename("pkg-0.1.0-py39h0.tar.bz2") == ("pkg", "0.1.0")


def test_parse_conda_filename_rejects_non_conda() -> None:
    with pytest.raises(specs.SpecError):
        specs.parse_conda_filename("pkg-1.0-py3-none-any.whl")
    with pytest.raises(specs.SpecError):
        specs.parse_conda_filename("pkg-1.0.conda")  # only two segments


@pytest.mark.parametrize("spec", ["pkg/1.0", "my-pkg/1.0.0", "pkg/1.0/pkg-1.0-h0.conda"])
def test_parse_spec_accepts_valid(spec: str) -> None:
    assert specs.parse_spec(spec)[0] == spec.split("/")[0]


@pytest.mark.parametrize(
    "spec",
    [
        "someorg/pkg/1.0",  # three segments, third is not a filename => owner smuggle
        "pkg/1.0/1.0",
        "pkg/1.0/file.txt",
    ],
)
def test_parse_spec_rejects_owner_qualified(spec: str) -> None:
    with pytest.raises(specs.SpecError, match="without an owner segment"):
        specs.parse_spec(spec)


@pytest.mark.parametrize("spec", ["pkg", "a/b/c/d", "", "pkg/", "/1.0"])
def test_parse_spec_rejects_malformed(spec: str) -> None:
    with pytest.raises(specs.SpecError):
        specs.parse_spec(spec)


def test_validate_owner_and_label() -> None:
    assert specs.validate_owner(" my-org ") == "my-org"
    for bad in ["", "has space", "-lead", "a/b"]:
        with pytest.raises(specs.SpecError):
            specs.validate_owner(bad)
    assert specs.validate_label("main", field="promote-label") == "main"
    with pytest.raises(specs.SpecError):
        specs.validate_label("", field="upload-label")
    with pytest.raises(specs.SpecError):
        specs.validate_label("bad/label", field="upload-label")


def test_parse_extra_arguments_rejects_owned_flags() -> None:
    assert specs.parse_extra_arguments("--no-register --summary hi", field="upload-arguments") == [
        "--no-register",
        "--summary",
        "hi",
    ]
    for smuggled in ["--force", "--skip-existing", "-l main", "--label=main", "-u org", "-t x"]:
        with pytest.raises(specs.SpecError, match="owned by typed inputs"):
            specs.parse_extra_arguments(smuggled, field="upload-arguments")


def test_validate_existing_mode() -> None:
    for mode in specs.EXISTING_MODES:
        assert specs.validate_existing_mode(mode) == mode
    with pytest.raises(specs.SpecError, match="must be one of"):
        specs.validate_existing_mode("clobber")


# --------------------------------------------------------------------------- #
# specs.py: digest verification                                               #
# --------------------------------------------------------------------------- #
def _conda_file(directory: Path, name: str, data: bytes) -> dict[str, object]:
    path = directory / "noarch" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "name": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "kind": "conda",
    }


def _manifest(files: list[dict[str, object]]) -> dict[str, object]:
    return {"schema": 1, "files": files, "artifacts": {"conda-channel": "chan"}}


def test_verify_files_success(tmp_path: Path) -> None:
    entry = _conda_file(tmp_path, "pkg-1.2.3-h0.conda", b"payload-a")
    verified = specs.verify_files_against_manifest(tmp_path, _manifest([entry]))
    assert [item.name for item in verified] == ["pkg-1.2.3-h0.conda"]
    assert verified[0].version == "1.2.3"
    assert specs.resolve_version(verified) == "1.2.3"


def test_verify_files_digest_mismatch(tmp_path: Path) -> None:
    entry = _conda_file(tmp_path, "pkg-1.0-h0.conda", b"real")
    entry["sha256"] = "0" * 64
    with pytest.raises(specs.SpecError, match="sha256 mismatch"):
        specs.verify_files_against_manifest(tmp_path, _manifest([entry]))


def test_verify_files_size_mismatch(tmp_path: Path) -> None:
    entry = _conda_file(tmp_path, "pkg-1.0-h0.conda", b"real")
    entry["size"] = 999
    with pytest.raises(specs.SpecError, match="size mismatch"):
        specs.verify_files_against_manifest(tmp_path, _manifest([entry]))


def test_verify_files_missing_file(tmp_path: Path) -> None:
    tmp_path.joinpath("noarch").mkdir()
    entry = {"name": "gone-1.0-h0.conda", "sha256": "0" * 64, "size": 1, "kind": "conda"}
    with pytest.raises(specs.SpecError, match="missing from"):
        specs.verify_files_against_manifest(tmp_path, _manifest([entry]))


def test_verify_files_unlisted_file(tmp_path: Path) -> None:
    listed = _conda_file(tmp_path, "pkg-1.0-h0.conda", b"real")
    _conda_file(tmp_path, "extra-1.0-h0.conda", b"surprise")
    with pytest.raises(specs.SpecError, match="not listed in the dist manifest"):
        specs.verify_files_against_manifest(tmp_path, _manifest([listed]))


def test_verify_files_wrong_kind(tmp_path: Path) -> None:
    good = _conda_file(tmp_path, "pkg-1.0-h0.conda", b"real")
    wrong = _conda_file(tmp_path, "other-1.0-h0.conda", b"other")
    wrong["kind"] = "wheel"  # a .conda file listed under a non-conda kind
    with pytest.raises(specs.SpecError, match="not 'conda'"):
        specs.verify_files_against_manifest(tmp_path, _manifest([good, wrong]))


def test_verify_files_no_conda_entries(tmp_path: Path) -> None:
    tmp_path.joinpath("noarch").mkdir()
    manifest: dict[str, object] = {
        "schema": 1,
        "files": [{"name": "w.whl", "sha256": "0", "size": 1, "kind": "wheel"}],
    }
    with pytest.raises(specs.SpecError, match="no conda packages"):
        specs.verify_files_against_manifest(tmp_path, manifest)


def test_resolve_version_rejects_mixed_and_honors_expected(tmp_path: Path) -> None:
    a = _conda_file(tmp_path, "pkg-1.0-h0.conda", b"a")
    b = _conda_file(tmp_path, "pkg-2.0-h0.conda", b"bb")
    verified = specs.verify_files_against_manifest(tmp_path, _manifest([a, b]))
    with pytest.raises(specs.SpecError, match="disagree on version"):
        specs.resolve_version(verified)


def test_resolve_version_expected_mismatch(tmp_path: Path) -> None:
    entry = _conda_file(tmp_path, "pkg-1.0-h0.conda", b"a")
    verified = specs.verify_files_against_manifest(tmp_path, _manifest([entry]))
    assert specs.resolve_version(verified, expected="1.0") == "1.0"
    with pytest.raises(specs.SpecError, match="does not match"):
        specs.resolve_version(verified, expected="9.9")


# --------------------------------------------------------------------------- #
# specs.py: argv construction                                                 #
# --------------------------------------------------------------------------- #
def test_build_argv_shapes() -> None:
    up = specs.build_upload_argv(
        server_url="",
        owner="org",
        label="staging",
        mode="overwrite",
        extra_arguments=["--no-register"],
        file_path="/x/p.conda",
    )
    assert up == [
        "anaconda",
        "upload",
        "--user",
        "org",
        "--label",
        "staging",
        "--force",
        "--no-register",
        "/x/p.conda",
    ]
    assert specs.build_upload_argv(
        server_url="https://s", owner="o", label="l", mode="fail", extra_arguments=[], file_path="f"
    )[:3] == ["anaconda", "-s", "https://s"]
    assert specs.build_move_argv(
        server_url="", from_label="staging", to_label="main", target="org/pkg/1.0"
    ) == ["anaconda", "move", "--from-label", "staging", "--to-label", "main", "org/pkg/1.0"]
    assert specs.build_remove_argv(server_url="", target="org/pkg/1.0") == [
        "anaconda",
        "remove",
        "--force",
        "org/pkg/1.0",
    ]
    assert specs.uvx_wrap("1.13.0", ["anaconda", "upload"])[:3] == [
        "uvx",
        "--from",
        "anaconda-client==1.13.0",
    ]


def test_resolve_client_version_uses_pin_or_override() -> None:
    assert specs.resolve_client_version("") == specs.ANACONDA_CLIENT_VERSION
    assert specs.resolve_client_version(" 2.0.0 ") == "2.0.0"


# --------------------------------------------------------------------------- #
# validate-inputs.py                                                          #
# --------------------------------------------------------------------------- #
_GOOD_MANIFEST = json.dumps(
    {
        "schema": 1,
        "files": [{"name": "pkg-1.0-h0.conda", "sha256": "0" * 64, "size": 1, "kind": "conda"}],
        "artifacts": {"conda-channel": "chan"},
    }
)


def _validate_env(**overrides: str) -> dict[str, str]:
    base = {
        "PUBLISH_OWNER": "devflows-fixture",
        "PUBLISH_DRY_RUN_ENABLED": "false",
        "PUBLISH_TIMEOUT_MINUTES": "15",
        "PUBLISH_EXPECTED_VERSION": "",
        "PUBLISH_DIST_MANIFEST": "",
        "PUBLISH_DIST_PATH": "",
        "UPLOAD_ENABLED": "false",
        "UPLOAD_LABEL": "staging",
        "UPLOAD_EXISTING_MODE": "fail",
        "UPLOAD_ARGUMENTS": "",
        "PROMOTE_ENABLED": "false",
        "PROMOTE_LABEL": "main",
        "PROMOTE_SPECS": "",
        "MAINTAIN_ENABLED": "false",
        "MAINTAIN_REMOVE_SPECS": "",
        "MAINTAIN_CONFIRM": "",
        "ARTIFACT_DOWNLOAD_ENABLED": "false",
        "ARTIFACT_DOWNLOAD_NAME": "",
    }
    base.update(overrides)
    return base


def _run_validate(monkeypatch, **overrides: str) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in _validate_env(**overrides).items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0


def _expect_validate_failure(monkeypatch, message: str, **overrides: str) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in _validate_env(**overrides).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert message in str(excinfo.value)


def test_validate_accepts_upload_call(monkeypatch) -> None:
    _run_validate(
        monkeypatch,
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_NAME="chan",
        PUBLISH_DIST_PATH="conda-channel",
        PUBLISH_DIST_MANIFEST=_GOOD_MANIFEST,
    )


def test_validate_accepts_maintain_dry_run(monkeypatch) -> None:
    _run_validate(
        monkeypatch,
        PUBLISH_DRY_RUN_ENABLED="true",
        UPLOAD_ENABLED="false",
        MAINTAIN_ENABLED="true",
        MAINTAIN_REMOVE_SPECS="pkg/1.0",
        MAINTAIN_CONFIRM="",
    )


def test_validate_accepts_promote_only(monkeypatch) -> None:
    _run_validate(
        monkeypatch,
        UPLOAD_ENABLED="false",
        PROMOTE_ENABLED="true",
        PROMOTE_SPECS="pkg/1.0",
    )


def test_validate_nothing_to_do(monkeypatch) -> None:
    _expect_validate_failure(monkeypatch, "Nothing to do")


def test_validate_maintain_not_exclusive(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch, "mutually exclusive", UPLOAD_ENABLED="true", MAINTAIN_ENABLED="true"
    )


def test_validate_bad_owner(monkeypatch) -> None:
    _expect_validate_failure(monkeypatch, "publish-owner", PUBLISH_OWNER="has space")


def test_validate_bad_timeout(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "positive",
        UPLOAD_ENABLED="false",
        MAINTAIN_ENABLED="true",
        MAINTAIN_REMOVE_SPECS="pkg/1.0",
        MAINTAIN_CONFIRM="devflows-fixture",
        PUBLISH_TIMEOUT_MINUTES="0",
    )


def test_validate_upload_requires_download(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "artifact-download-enabled is false",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="false",
    )


def test_validate_upload_requires_dist_path(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "publish-dist-path is required",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        PUBLISH_DIST_PATH="",
    )


def test_validate_dist_path_traversal(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "workspace-relative",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        PUBLISH_DIST_PATH="../escape",
    )


def test_validate_upload_without_manifest(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "publish-dist-manifest is required",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        PUBLISH_DIST_PATH="c",
    )


def test_validate_malformed_manifest(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "not valid JSON",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        PUBLISH_DIST_PATH="c",
        PUBLISH_DIST_MANIFEST="{not json",
    )


def test_validate_manifest_artifact_mismatch(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "does not match artifact-download-name",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_NAME="other",
        PUBLISH_DIST_PATH="c",
        PUBLISH_DIST_MANIFEST=_GOOD_MANIFEST,
    )


def test_validate_manifest_no_conda(monkeypatch) -> None:
    manifest = json.dumps(
        {"schema": 1, "files": [{"name": "w.whl", "sha256": "0", "size": 1, "kind": "wheel"}]}
    )
    _expect_validate_failure(
        monkeypatch,
        "contains no conda packages",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        PUBLISH_DIST_PATH="c",
        PUBLISH_DIST_MANIFEST=manifest,
    )


def test_validate_forbidden_upload_argument(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "owned by typed inputs",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        PUBLISH_DIST_PATH="c",
        PUBLISH_DIST_MANIFEST=_GOOD_MANIFEST,
        UPLOAD_ARGUMENTS="--force",
    )


def test_validate_bad_existing_mode(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "must be one of fail, skip, overwrite",
        UPLOAD_ENABLED="true",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        PUBLISH_DIST_PATH="c",
        PUBLISH_DIST_MANIFEST=_GOOD_MANIFEST,
        UPLOAD_EXISTING_MODE="clobber",
    )


def test_validate_promote_only_without_specs(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "promote-specs is required",
        UPLOAD_ENABLED="false",
        PROMOTE_ENABLED="true",
        PROMOTE_SPECS="",
    )


def test_validate_spec_with_owner(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "without an owner segment",
        UPLOAD_ENABLED="false",
        PROMOTE_ENABLED="true",
        PROMOTE_SPECS="someorg/pkg/1.0",
    )


def test_validate_label_collision(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "must differ",
        UPLOAD_ENABLED="false",
        PROMOTE_ENABLED="true",
        PROMOTE_SPECS="pkg/1.0",
        UPLOAD_LABEL="main",
        PROMOTE_LABEL="main",
    )


def test_validate_maintain_unconfirmed(monkeypatch) -> None:
    _expect_validate_failure(
        monkeypatch,
        "maintain-confirm must equal publish-owner",
        UPLOAD_ENABLED="false",
        MAINTAIN_ENABLED="true",
        MAINTAIN_REMOVE_SPECS="pkg/1.0",
        MAINTAIN_CONFIRM="",
    )


def test_validate_maintain_confirmed(monkeypatch) -> None:
    _run_validate(
        monkeypatch,
        UPLOAD_ENABLED="false",
        MAINTAIN_ENABLED="true",
        MAINTAIN_REMOVE_SPECS="pkg/1.0",
        MAINTAIN_CONFIRM="devflows-fixture",
    )


# --------------------------------------------------------------------------- #
# verify-dist.py: plan computation and output emission                        #
# --------------------------------------------------------------------------- #
def _verify_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    base = {
        "PUBLISH_OWNER": "devflows-fixture",
        "PUBLISH_SERVER_URL": "",
        "PUBLISH_CLIENT_VERSION": "",
        "PUBLISH_DIST_PATH": str(tmp_path),
        "PUBLISH_DIST_MANIFEST": "",
        "PUBLISH_EXPECTED_VERSION": "",
        "GITHUB_WORKSPACE": str(tmp_path),
        "UPLOAD_ENABLED": "false",
        "UPLOAD_LABEL": "staging",
        "UPLOAD_EXISTING_MODE": "fail",
        "UPLOAD_ARGUMENTS": "",
        "PROMOTE_ENABLED": "false",
        "PROMOTE_LABEL": "main",
        "PROMOTE_SPECS": "",
        "MAINTAIN_ENABLED": "false",
        "MAINTAIN_REMOVE_SPECS": "",
        "EMIT_PLAN": "true",
    }
    base.update(overrides)
    return base


def _run_verify(monkeypatch, tmp_path: Path, output: Path, **overrides: str) -> dict[str, str]:
    module = _load_script("verify-dist.py")
    for key, value in _verify_env(tmp_path, **overrides).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert module.main() == 0
    if not output.exists():
        return {}
    return _parse_github_output(output)


def test_verify_upload_and_promote_plan(monkeypatch, tmp_path: Path) -> None:
    entry = _conda_file(tmp_path, "pkg-1.2.3-h0.conda", b"payload")
    output = tmp_path / "out.txt"
    parsed = _run_verify(
        monkeypatch,
        tmp_path,
        output,
        UPLOAD_ENABLED="true",
        PROMOTE_ENABLED="true",
        PUBLISH_DIST_MANIFEST=json.dumps(_manifest([entry])),
    )
    assert parsed["package-version"] == "1.2.3"
    assert parsed["staged-specs"] == "devflows-fixture/pkg/1.2.3"
    assert parsed["uploaded-files"] == "pkg-1.2.3-h0.conda"
    # Chained promote derives the exact staged specs.
    assert parsed["promoted-specs"] == "devflows-fixture/pkg/1.2.3"
    assert parsed["removed-specs"] == ""


def test_verify_promote_only(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.txt"
    parsed = _run_verify(
        monkeypatch,
        tmp_path,
        output,
        UPLOAD_ENABLED="false",
        PROMOTE_ENABLED="true",
        PROMOTE_SPECS="pkg/1.0\nother/2.0",
    )
    assert parsed["staged-specs"] == ""
    assert parsed["package-version"] == ""
    assert parsed["promoted-specs"] == "devflows-fixture/pkg/1.0\ndevflows-fixture/other/2.0"


def test_verify_maintain_plan(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.txt"
    parsed = _run_verify(
        monkeypatch,
        tmp_path,
        output,
        UPLOAD_ENABLED="false",
        MAINTAIN_ENABLED="true",
        MAINTAIN_REMOVE_SPECS="pkg/1.0\npkg/0.9/pkg-0.9-h0.conda",
    )
    assert parsed["removed-specs"] == (
        "devflows-fixture/pkg/1.0\ndevflows-fixture/pkg/0.9/pkg-0.9-h0.conda"
    )


def test_verify_expected_version_guard(monkeypatch, tmp_path: Path) -> None:
    entry = _conda_file(tmp_path, "pkg-1.2.3-h0.conda", b"payload")
    output = tmp_path / "out.txt"
    module = _load_script("verify-dist.py")
    for key, value in _verify_env(
        tmp_path,
        UPLOAD_ENABLED="true",
        PUBLISH_EXPECTED_VERSION="9.9.9",
        PUBLISH_DIST_MANIFEST=json.dumps(_manifest([entry])),
    ).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    with pytest.raises(SystemExit, match="does not match"):
        module.main()


def test_verify_reverify_mode_emits_nothing(monkeypatch, tmp_path: Path) -> None:
    entry = _conda_file(tmp_path, "pkg-1.0-h0.conda", b"payload")
    output = tmp_path / "out.txt"
    parsed = _run_verify(
        monkeypatch,
        tmp_path,
        output,
        EMIT_PLAN="false",
        UPLOAD_ENABLED="true",
        PUBLISH_DIST_MANIFEST=json.dumps(_manifest([entry])),
    )
    # EMIT_PLAN=false still verifies (would raise on mismatch) but emits no outputs.
    assert parsed == {}


def test_verify_reverify_mode_still_fails_on_mismatch(monkeypatch, tmp_path: Path) -> None:
    entry = _conda_file(tmp_path, "pkg-1.0-h0.conda", b"payload")
    entry["sha256"] = "0" * 64
    output = tmp_path / "out.txt"
    module = _load_script("verify-dist.py")
    for key, value in _verify_env(
        tmp_path,
        EMIT_PLAN="false",
        UPLOAD_ENABLED="true",
        PUBLISH_DIST_MANIFEST=json.dumps(_manifest([entry])),
    ).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        module.main()


# --------------------------------------------------------------------------- #
# preflight-token.py                                                           #
# --------------------------------------------------------------------------- #
def test_preflight_requires_token_when_not_dry_run(monkeypatch) -> None:
    module = _load_script("preflight-token.py")
    monkeypatch.setenv("PUBLISH_DRY_RUN_ENABLED", "false")
    monkeypatch.setenv("ANACONDA_TOKEN_PRESENT", "false")
    with pytest.raises(SystemExit, match="anaconda-token secret is empty"):
        module.main()
    monkeypatch.setenv("ANACONDA_TOKEN_PRESENT", "true")
    assert module.main() == 0
    # A dry-run never reaches these jobs, but the belt-and-suspenders guard passes.
    monkeypatch.setenv("PUBLISH_DRY_RUN_ENABLED", "true")
    monkeypatch.setenv("ANACONDA_TOKEN_PRESENT", "false")
    assert module.main() == 0


# --------------------------------------------------------------------------- #
# Renovate pin registration                                                   #
# --------------------------------------------------------------------------- #
def test_anaconda_client_pin_matches_renovate_manager() -> None:
    # The pinned version must be a plausible PEP440 release.
    assert re.fullmatch(r"[0-9]+(\.[0-9]+)*", specs.ANACONDA_CLIENT_VERSION)
    renovate = (REPO / "renovate.json5").read_text(encoding="utf-8")
    assert "workflows/anaconda-publish/scripts/specs" in renovate
    assert "depName=(?<depName>" in renovate  # the pep440 manager is registered
    # The regex Renovate is configured with must actually match the constant so the
    # pin keeps auto-updating; mirror it here (double-escapes collapse to one).
    manager_regex = (
        r"# renovate: datasource=(?P<datasource>\S+) depName=(?P<depName>\S+)\s+"
        r'ANACONDA_CLIENT_VERSION = "(?P<currentValue>[^"]+)"'
    )
    source = (SCRIPT_DIR / "specs.py").read_text(encoding="utf-8")
    match = re.search(manager_regex, source)
    assert match is not None
    assert match.group("depName") == "anaconda-client"
    assert match.group("datasource") == "pypi"
    assert match.group("currentValue") == specs.ANACONDA_CLIENT_VERSION


# --------------------------------------------------------------------------- #
# Workflow shape: least-exposure, gating, environments                        #
# --------------------------------------------------------------------------- #
def _published() -> dict:
    return build_published_workflow(load_workflow(REPO / "workflows" / "anaconda-publish"))


def _steps(job: dict) -> list[dict]:
    return [step for step in job.get("steps", []) if isinstance(step, dict)]


def test_caller_required_permissions_are_read_only() -> None:
    assert caller_required_permissions(_published()) == {"actions": "read", "contents": "read"}


def test_token_on_exactly_one_step_per_credentialed_job() -> None:
    jobs = _published()["jobs"]
    for job_id in ("upload", "promote", "maintain"):
        token_steps = [
            step for step in _steps(jobs[job_id]) if "ANACONDA_API_TOKEN" in (step.get("env") or {})
        ]
        assert len(token_steps) == 1, job_id
        # The token never rides on a download, materialize, verify, or preflight step.
        for step in _steps(jobs[job_id]):
            name = str(step.get("name", "")).lower()
            if step is token_steps[0]:
                continue
            assert "ANACONDA_API_TOKEN" not in (step.get("env") or {}), (job_id, name)
    # The verify job (credential-free) never sees the token at all.
    for step in _steps(jobs["verify"]):
        assert "ANACONDA_API_TOKEN" not in (step.get("env") or {})


def test_credentialed_jobs_bind_environment_and_serial_concurrency() -> None:
    jobs = _published()["jobs"]
    bindings = {
        "upload": "upload-environment-name",
        "promote": "promote-environment-name",
        "maintain": "maintain-environment-name",
    }
    for job_id, input_name in bindings.items():
        job = jobs[job_id]
        assert job["environment"]["name"] == f"${{{{ inputs.{input_name} }}}}"
        assert job["concurrency"]["group"] == f"anaconda-publish-${{{{ inputs.{input_name} }}}}"
        assert job["concurrency"]["cancel-in-progress"] is False
        # Dry-run skips every environment-bound job at the job level.
        assert "!inputs.publish-dry-run-enabled" in job["if"]


def test_validate_and_verify_never_bind_environment() -> None:
    jobs = _published()["jobs"]
    for job_id in ("validate", "verify"):
        assert "environment" not in jobs[job_id]
        assert "if" not in jobs[job_id]


def test_promote_never_runs_on_partial_upload() -> None:
    condition = _published()["jobs"]["promote"]["if"]
    assert "needs.verify.result == 'success'" in condition
    assert "needs.upload.result == 'success' || needs.upload.result == 'skipped'" in condition


def test_preflight_is_tokenless() -> None:
    jobs = _published()["jobs"]
    for job_id in ("upload", "promote", "maintain"):
        preflight = next(
            step
            for step in _steps(jobs[job_id])
            if step.get("name") == "Assert publishing credential present"
        )
        env = preflight.get("env") or {}
        assert env["ANACONDA_TOKEN_PRESENT"] == "${{ secrets.anaconda-token != '' }}"
        assert "ANACONDA_API_TOKEN" not in env
