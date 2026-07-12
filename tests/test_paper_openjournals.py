"""Unit tests for the paper-openjournals workflow scripts and interface.

Covers common.py (every validation branch), run-inara.py (docker argv assembly,
per-flavor collection, output emission, and its failure paths), validate-inputs.py,
the published-workflow interface snapshot, injection-safety of the generated
run: blocks, the size cap, and the Renovate image-pin manager.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from devflows.catalog import load_catalog, load_workflow
from devflows.publish import (
    MAX_GENERATED_WORKFLOW_BYTES,
    build_published_workflow,
    render_published_workflow,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO / "workflows" / "paper-openjournals" / "scripts"

# The workflow scripts import their sibling common module (materialized next to
# them at run time); make it importable here too.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import common  # type: ignore  # noqa: E402


def _load_script(name: str) -> ModuleType:
    path = SCRIPT_DIR / name
    module_name = "paper_openjournals_" + name.replace("-", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _base_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = {
        "GITHUB_WORKSPACE": str(tmp_path),
        "PAPER_JOURNAL": "joss",
        "PAPER_SOURCE_PATH": "docs/paper.md",
        "PAPER_FLAVORS": "cff",
        "PAPER_IMAGE": "ghcr.io/openjournals/inara:1.3.1",
        "PAPER_OUTPUT_DIRECTORY": "paper-build",
        "PAPER_ARGUMENTS": "",
    }
    env.update(overrides)
    return env


# --------------------------------------------------------------------------- #
# Journal enum                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,expected",
    [("joss", "joss"), ("jose", "jose"), ("rescience-c", "resciencec")],
)
def test_journal_maps_to_upstream_resource_name(tmp_path, value, expected) -> None:
    config = common.parse_and_validate(
        _base_env(tmp_path, PAPER_JOURNAL=value), require_source_exists=False
    )
    assert config.journal_env == expected


@pytest.mark.parametrize("value", ["", "  ", "elsevier", "JOSS", "rescience c"])
def test_invalid_journal_is_rejected(tmp_path, value) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_JOURNAL=value), require_source_exists=False
        )
    assert "must be one of" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Image reference                                                             #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/openjournals/inara:1.3.1",
        "openjournals/inara",
        "docker.io/openjournals/inara:latest",
        "ghcr.io/openjournals/inara@sha256:" + "a" * 64,
        "myregistry.com:5000/team/inara",
    ],
)
def test_valid_image_references_are_accepted(tmp_path, image) -> None:
    config = common.parse_and_validate(
        _base_env(tmp_path, PAPER_IMAGE=image), require_source_exists=False
    )
    assert config.image == image


@pytest.mark.parametrize(
    "image",
    ["", "   ", "inara:bad:ref", "openjournals//inara", "/openjournals/inara", "inara:bad tag"],
)
def test_malformed_image_references_are_rejected(tmp_path, image) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_IMAGE=image), require_source_exists=False
        )
    assert "valid image reference" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Flavors                                                                     #
# --------------------------------------------------------------------------- #
def test_flavors_are_parsed_deduplicated_and_ordered(tmp_path) -> None:
    config = common.parse_and_validate(
        _base_env(tmp_path, PAPER_FLAVORS="jats\ncff\njats\n  \ndraft-pdf"),
        require_source_exists=False,
    )
    assert config.flavors == ("jats", "cff", "draft-pdf")


@pytest.mark.parametrize("value", ["", "   ", "\n\n"])
def test_empty_flavors_is_rejected(tmp_path, value) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_FLAVORS=value), require_source_exists=False
        )
    assert "at least one paper flavor" in str(excinfo.value)


def test_unknown_flavor_is_rejected(tmp_path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_FLAVORS="draft-pdf\ngif"),
            require_source_exists=False,
        )
    assert "unknown paper flavor: gif" in str(excinfo.value)


def test_native_flavor_is_not_in_the_vocabulary(tmp_path) -> None:
    # native streams to stdout with no output-file, so it is excluded on purpose.
    assert "native" not in common.FLAVORS
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_FLAVORS="native"), require_source_exists=False
        )
    assert "unknown paper flavor: native" in str(excinfo.value)


def test_flavor_table_matches_the_design_argv_and_outputs() -> None:
    assert set(common.FLAVORS) == {
        "draft-pdf",
        "final-pdf",
        "jats",
        "crossref",
        "cff",
        "html",
        "preprint",
        "tex",
        "docx",
        "context-pdf",
    }
    assert common.FLAVORS["draft-pdf"].argv == ("-o", "pdf")
    assert common.FLAVORS["final-pdf"].argv == ("-p", "-o", "pdf")
    assert common.FLAVORS["context-pdf"].argv == ("-o", "contextpdf")
    # draft and final PDFs both write paper.pdf, which is why each flavor lands
    # in its own subdirectory.
    assert common.FLAVORS["draft-pdf"].outputs[0].name == "paper.pdf"
    assert common.FLAVORS["final-pdf"].outputs[0].name == "paper.pdf"
    assert common.FLAVORS["cff"].outputs[0].name == "CITATION.cff"
    assert common.FLAVORS["jats"].outputs[0].name == "jats"
    # html carries an optional media directory.
    html_outputs = {o.name: o.required for o in common.FLAVORS["html"].outputs}
    assert html_outputs == {"paper.html": True, "media": False}
    # Every non-native format defaults file has a fixed, source-independent name.
    for flavor in common.FLAVORS.values():
        assert any(output.required for output in flavor.outputs)


# --------------------------------------------------------------------------- #
# Source path containment                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", [None, ""])
def test_missing_github_workspace_raises_clear_error(tmp_path, value) -> None:
    # GITHUB_WORKSPACE anchors every containment check; an unset (or empty) value
    # must raise a clear SystemExit rather than a bare KeyError (binder parity).
    env = _base_env(tmp_path)
    if value is None:
        del env["GITHUB_WORKSPACE"]
    else:
        env["GITHUB_WORKSPACE"] = value
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(env, require_source_exists=False)
    assert "GITHUB_WORKSPACE is not set" in str(excinfo.value)


def test_empty_source_path_is_rejected(tmp_path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_SOURCE_PATH=""), require_source_exists=False
        )
    assert "paper-source-path is required" in str(excinfo.value)


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../outside.md", "../../../etc/passwd", "docs/../../escape.md"],
)
def test_source_path_escaping_workspace_is_rejected(tmp_path, path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_SOURCE_PATH=path), require_source_exists=False
        )
    assert "must stay inside" in str(excinfo.value)


def test_source_path_is_normalized_to_workspace_relative(tmp_path) -> None:
    config = common.parse_and_validate(
        _base_env(tmp_path, PAPER_SOURCE_PATH="./docs/paper.md"),
        require_source_exists=False,
    )
    assert config.source_relative == "docs/paper.md"


def test_require_source_exists_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_SOURCE_PATH="docs/paper.md"),
            require_source_exists=True,
        )
    assert "does not exist" in str(excinfo.value)


def test_require_source_exists_rejects_directory(tmp_path) -> None:
    (tmp_path / "docs").mkdir()
    with pytest.raises(SystemExit):
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_SOURCE_PATH="docs"),
            require_source_exists=True,
        )


def test_require_source_exists_accepts_regular_file(tmp_path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "paper.md").write_text("# paper\n", encoding="utf-8")
    config = common.parse_and_validate(
        _base_env(tmp_path, PAPER_SOURCE_PATH="docs/paper.md"),
        require_source_exists=True,
    )
    assert config.source_relative == "docs/paper.md"


# --------------------------------------------------------------------------- #
# Output directory containment                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/abs/out", "../out", "a/../../out"])
def test_output_directory_escaping_workspace_is_rejected(tmp_path, path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_and_validate(
            _base_env(tmp_path, PAPER_OUTPUT_DIRECTORY=path),
            require_source_exists=False,
        )
    assert "must stay inside" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# paper-arguments allowlist                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", []),
        ("-v", ["-v"]),
        ("-v -v", ["-v", "-v"]),
        ("-l", ["-l"]),
        ("-vl", ["-v", "-l"]),
        ("-m info.yaml", ["-m", "info.yaml"]),
        ("-minfo.yaml", ["-m", "info.yaml"]),
        ("-v -m info.yaml -l", ["-v", "-m", "info.yaml", "-l"]),
    ],
)
def test_allowed_arguments_are_accepted(raw, expected) -> None:
    assert common.parse_extra_arguments(raw) == expected


@pytest.mark.parametrize("raw", ["-o pdf", "-p", "-r", "-opdf", "-vo", "-o=pdf", "-rp"])
def test_owned_flags_are_rejected_in_every_form(raw) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_extra_arguments(raw)
    assert "controlled by paper-flavors" in str(excinfo.value)


@pytest.mark.parametrize("raw", ["paper2.md", "-v extra.md", "--", "-v -- foo"])
def test_bare_positionals_are_rejected(raw) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_extra_arguments(raw)
    assert "positional" in str(excinfo.value)


@pytest.mark.parametrize("raw", ["-x", "-vx", "--verbose"])
def test_unknown_flags_are_rejected(raw) -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_extra_arguments(raw)
    assert "unsupported argument" in str(excinfo.value)


def test_value_flag_without_value_is_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_extra_arguments("-m")
    assert "requires a value" in str(excinfo.value)


def test_unbalanced_quotes_are_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        common.parse_extra_arguments("-m 'unterminated")
    assert "Unable to parse paper-arguments" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# run-inara.py: docker argv, collection, outputs                              #
# --------------------------------------------------------------------------- #
_FORMAT_OUTPUTS = {
    "pdf": ["paper.pdf"],
    "jats": ["jats/paper.jats"],
    "crossref": ["paper.crossref"],
    "cff": ["CITATION.cff"],
    "html": ["paper.html", "media/image.png"],
    "preprint": ["paper.preprint.tex"],
    "tex": ["paper.tex"],
    "docx": ["paper.docx"],
    "contextpdf": ["paper.context.pdf"],
}


def _fake_docker(source_directory: Path, recorder: list[list[str]]):
    """A subprocess.run stand-in that records the argv and writes fake outputs."""

    def _run(command, *, check):  # noqa: ANN001
        recorder.append(list(command))
        fmt = command[command.index("-o") + 1]
        for relative in _FORMAT_OUTPUTS[fmt]:
            produced = source_directory / relative
            produced.parent.mkdir(parents=True, exist_ok=True)
            produced.write_text(f"fake {fmt} output\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    return _run


def _prepare_workspace(tmp_path: Path) -> Path:
    source_directory = tmp_path / "docs"
    source_directory.mkdir()
    (source_directory / "paper.md").write_text("# paper\n", encoding="utf-8")
    return source_directory


def test_run_inara_builds_expected_docker_argv(tmp_path, monkeypatch) -> None:
    source_directory = _prepare_workspace(tmp_path)
    module = _load_script("run-inara.py")
    recorder: list[list[str]] = []
    monkeypatch.setattr(module.subprocess, "run", _fake_docker(source_directory, recorder))
    for key, value in _base_env(
        tmp_path,
        PAPER_JOURNAL="rescience-c",
        PAPER_FLAVORS="draft-pdf",
        PAPER_ARGUMENTS="-v",
    ).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))

    assert module.main() == 0
    command = recorder[0]
    assert command[:4] == ["docker", "run", "--rm", "--user"]
    assert "--volume" in command and f"{tmp_path}:/data" in command
    assert command[command.index("--workdir") + 1] == "/data"
    assert command[command.index("--env") + 1] == "JOURNAL=resciencec"
    assert command[command.index("--env") + 2] == "ghcr.io/openjournals/inara:1.3.1"
    # argv order: image, flavor argv, extra args, source positional (last).
    assert command[-1] == "docs/paper.md"
    assert command[-2] == "-v"
    assert command.index("-o") < command.index("pdf") < len(command) - 1


def test_run_inara_collects_each_flavor_into_its_own_subdirectory(tmp_path, monkeypatch) -> None:
    source_directory = _prepare_workspace(tmp_path)
    module = _load_script("run-inara.py")
    recorder: list[list[str]] = []
    monkeypatch.setattr(module.subprocess, "run", _fake_docker(source_directory, recorder))
    for key, value in _base_env(tmp_path, PAPER_FLAVORS="draft-pdf\nfinal-pdf\njats\nhtml").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))

    assert module.main() == 0
    out = tmp_path / "paper-build"
    # draft/final PDFs never collide: each has its own subdirectory.
    assert (out / "draft-pdf" / "paper.pdf").is_file()
    assert (out / "final-pdf" / "paper.pdf").is_file()
    # JATS keeps its jats/ subfolder (so the artifact path is jats/jats/paper.jats).
    assert (out / "jats" / "jats" / "paper.jats").is_file()
    # html collects the optional media directory too.
    assert (out / "html" / "paper.html").is_file()
    assert (out / "html" / "media" / "image.png").is_file()
    # Produced files are moved out of the source tree.
    assert not (source_directory / "paper.pdf").exists()
    assert not (source_directory / "jats").exists()


def test_run_inara_writes_job_outputs(tmp_path, monkeypatch) -> None:
    source_directory = _prepare_workspace(tmp_path)
    module = _load_script("run-inara.py")
    recorder: list[list[str]] = []
    monkeypatch.setattr(module.subprocess, "run", _fake_docker(source_directory, recorder))
    output_file = tmp_path / "out.txt"
    for key, value in _base_env(tmp_path, PAPER_FLAVORS="cff\njats").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    assert module.main() == 0
    text = output_file.read_text(encoding="utf-8")
    assert "paper-output-directory=paper-build\n" in text
    assert "flavors-built<<DEVFLOWS_EOF\ncff\njats\nDEVFLOWS_EOF\n" in text


def test_run_inara_rejects_nonempty_output_directory(tmp_path, monkeypatch) -> None:
    _prepare_workspace(tmp_path)
    stale = tmp_path / "paper-build" / "cff"
    stale.mkdir(parents=True)
    (stale / "CITATION.cff").write_text("stale\n", encoding="utf-8")
    module = _load_script("run-inara.py")
    monkeypatch.setattr(
        module.subprocess, "run", lambda command, *, check: pytest.fail("must not run")
    )
    for key, value in _base_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "already exists and is not empty" in str(excinfo.value)


def test_run_inara_fails_when_required_output_missing(tmp_path, monkeypatch) -> None:
    _prepare_workspace(tmp_path)
    module = _load_script("run-inara.py")
    # A docker stand-in that produces nothing.
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, *, check: subprocess.CompletedProcess(command, 0),
    )
    for key, value in _base_env(tmp_path, PAPER_FLAVORS="cff").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))

    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "did not produce its expected output" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# validate-inputs.py                                                          #
# --------------------------------------------------------------------------- #
def test_validate_inputs_main_accepts_valid_inputs(tmp_path, monkeypatch, capsys) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in _base_env(tmp_path, PAPER_FLAVORS="draft-pdf\njats").items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    assert "inputs are valid" in capsys.readouterr().out


def test_validate_inputs_main_rejects_bad_inputs(tmp_path, monkeypatch) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in _base_env(tmp_path, PAPER_JOURNAL="elsevier").items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit):
        module.main()


# --------------------------------------------------------------------------- #
# Published interface snapshot                                                #
# --------------------------------------------------------------------------- #
def _published() -> dict[str, Any]:
    for item in load_catalog():
        if item.id == "paper-openjournals":
            return build_published_workflow(item)
    raise AssertionError("paper-openjournals workflow not found in catalog")


def _workflow_call(published: dict[str, Any]) -> dict[str, Any]:
    return published["on"]["workflow_call"]


def test_domain_inputs_match_the_design() -> None:
    inputs = _workflow_call(_published())["inputs"]
    domain = {
        "paper-journal",
        "paper-source-path",
        "paper-flavors",
        "paper-image",
        "paper-output-directory",
        "paper-arguments",
        "paper-timeout-minutes",
    }
    assert domain <= set(inputs)
    assert inputs["paper-journal"]["required"] is True
    assert inputs["paper-source-path"]["required"] is True
    assert inputs["paper-image"]["default"] == "ghcr.io/openjournals/inara:1.3.1"
    assert inputs["paper-timeout-minutes"]["default"] == 30
    # Channel inputs are generator-injected (checkout + both artifact channels),
    # writeback is NOT (io.writeback is false).
    channels = {"checkout-enabled", "artifact-download-enabled", "artifact-upload-enabled"}
    assert channels <= set(inputs)
    assert "commit-enabled" not in inputs


def test_outputs_echo_the_build_job() -> None:
    outputs = _workflow_call(_published())["outputs"]
    assert set(outputs) == {"paper-output-directory", "flavors-built", "job-outputs"}
    assert outputs["paper-output-directory"]["value"] == (
        "${{ jobs.build.outputs.paper-output-directory }}"
    )
    assert outputs["flavors-built"]["value"] == "${{ jobs.build.outputs.flavors-built }}"
    assert outputs["job-outputs"]["value"] == "${{ jobs.build.outputs.job-outputs }}"


def test_permissions_are_least_privilege() -> None:
    published = _published()
    assert published["permissions"] == {}
    assert published["jobs"]["validate"]["permissions"] == {}
    # Build needs contents: read (checkout) and actions: read (artifact-download).
    assert published["jobs"]["build"]["permissions"] == {
        "contents": "read",
        "actions": "read",
    }
    # No write scopes, no id-token anywhere.
    for job in published["jobs"].values():
        perms = job.get("permissions", {})
        assert "write" not in " ".join(f"{k}:{v}" for k, v in perms.items())
        assert "id-token" not in perms


def test_build_needs_validate_and_no_secrets() -> None:
    published = _published()
    assert published["jobs"]["build"]["needs"] == "validate"
    # No domain secrets are declared; only the shared checkout-token channel secret.
    secrets = _workflow_call(published).get("secrets", {})
    assert "paper-token" not in secrets
    assert set(secrets) <= {
        "checkout-token",
        "checkout-ssh-key",
        "artifact-download-token",
    }


def test_no_input_is_interpolated_into_a_run_block() -> None:
    # The draft's core defect: inputs interpolated into run: text. Every input
    # must reach a script only through env.
    for job in _published()["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run")
            if isinstance(run, str):
                assert "${{ inputs." not in run
                assert "${{ matrix." not in run


def test_validate_step_env_maps_only_inputs() -> None:
    # Required so the validation-failure scenario harness can reconstruct the env.
    validate = _published()["jobs"]["validate"]
    step = next(s for s in validate["steps"] if s.get("name") == "Validate inputs")
    for key, value in step["env"].items():
        if key == "DEVFLOWS_SCRIPT_ROOT":
            continue
        assert re.fullmatch(r"\$\{\{ inputs\.[a-z0-9-]+ \}\}", value), (key, value)


def test_generated_workflow_is_under_the_size_cap() -> None:
    rendered = render_published_workflow(
        next(item for item in load_catalog() if item.id == "paper-openjournals")
    )
    assert len(rendered.encode("utf-8")) < MAX_GENERATED_WORKFLOW_BYTES


# --------------------------------------------------------------------------- #
# Renovate image pin                                                          #
# --------------------------------------------------------------------------- #
def test_image_pin_matches_renovate_manager() -> None:
    workflow = load_workflow(REPO / "workflows" / "paper-openjournals")
    default = workflow.workflow_call["inputs"]["paper-image"]["default"]
    assert default == "ghcr.io/openjournals/inara:1.3.1"

    renovate = (REPO / "renovate.json5").read_text(encoding="utf-8")
    assert "workflows/paper-openjournals/workflow" in renovate
    # Pull Renovate's ACTUAL configured matchString for the inara image out of
    # renovate.json5 and apply it to the source workflow.yaml, proving the manager
    # still matches the pinned default so the tag keeps auto-updating.
    # Anchor on `# renovate:` (the matchString body's first token) and stop at
    # either quote character, so the extraction is stable whether Prettier keeps
    # the JSON5 string single- or double-quoted and cannot start inside the
    # surrounding comment (which also names the image, but is quote-separated).
    match_strings = re.findall(r"(# renovate:[^\"']*openjournals/inara[^\"']*)", renovate)
    assert len(match_strings) == 1, "expected exactly one inara image matchString"
    configured = match_strings[0].replace("\\\\", "\\")  # JSON5 unescape
    python_pattern = re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", configured)
    source = (SCRIPT_DIR.parent / "workflow.yaml").read_text(encoding="utf-8")
    match = re.search(python_pattern, source)
    assert match is not None, python_pattern
    assert match.group("datasource") == "docker"
    assert match.group("depName") == "ghcr.io/openjournals/inara"
    assert match.group("currentValue") == "1.3.1"
