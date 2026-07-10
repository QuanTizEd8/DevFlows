"""Run the python-lint tools, render the report, set outputs, and enforce.

A single orchestrator step so job outputs and the job summary are always
populated -- each tool is run, its result recorded, and only then does the step
decide whether to fail. Tool findings (exit 1) never crash the step on their
own; the step exits nonzero only when a tool crashed (exit >= 2 / internal
error, which fails regardless of lint-enforce) or when lint-enforce is true and
any enabled tool reported findings. All caller strings arrive via env vars and
are shlex-split here; nothing is interpolated into a shell.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Tool-specific command name, executed argv prefix, and per-target-version flag.
# The package name equals the command name for all three (so one entry covers both
# the uvx package spec and the uv-run --with requirement), but the EXECUTED command
# is the argv prefix: ty's CLI requires a mandatory 'check' subcommand, so its argv
# is ["ty", "check"] while its package spec stays 'ty@<ver>'. mypy/pyright invoke
# the bare command. argv[0] is always the command name.
_TYPECHECKERS = {
    "mypy": {"command": "mypy", "argv": ["mypy"], "version_flag": "--python-version"},
    "pyright": {"command": "pyright", "argv": ["pyright"], "version_flag": "--pythonversion"},
    "ty": {"command": "ty", "argv": ["ty", "check"], "version_flag": "--python-version"},
}
_SUMMARY_DIFF_CAP = 30_000  # keep GITHUB_STEP_SUMMARY well under the 1 MiB limit
_ANNOTATION_CAP = 10  # GitHub renders at most ~10 annotations per step
_REFORMAT_COUNT = re.compile(r"(\d+)\s+files?\s+would\s+be\s+reformatted")
# mypy: file:line: error: msg  (column optional). pyright: file:line:col - error: msg.
_MYPY_ERROR = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*error:", re.MULTILINE
)
_PYRIGHT_ERROR = re.compile(
    r"^\s*(?P<file>.+?):(?P<line>\d+):(?P<col>\d+)\s+-\s+error:", re.MULTILINE
)


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class ToolOutcome:
    outcome: str = "skipped"
    crashed: bool = False
    annotations: list[dict[str, str]] = field(default_factory=list)


def main() -> int:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    working_directory = (workspace / (_get("LINT_WORKING_DIRECTORY") or ".")).resolve()
    enforce = _truthy(_get("LINT_ENFORCE"))
    annotations_enabled = _truthy(_get("LINT_ANNOTATIONS_ENABLED"))
    sync_enabled = _truthy(_get("LINT_UV_SYNC_ENABLED"))
    ruff_version = _get("LINT_RUFF_VERSION")
    paths = _split_lines(_get("LINT_PATHS")) or ["."]

    if sync_enabled:
        _uv_sync(working_directory)

    results: dict[str, dict[str, object]] = {}
    summary_sections: list[str] = []
    annotations: list[dict[str, str]] = []

    ruff_check = ToolOutcome()
    if _truthy(_get("LINT_RUFF_CHECK_ENABLED")):
        ruff_check, violations, report = _run_ruff_check(
            working_directory, workspace, paths, ruff_version, sync_enabled
        )
        results["ruff-check"] = {"outcome": ruff_check.outcome, "violations": violations}
        summary_sections.append(_ruff_check_summary(ruff_check.outcome, violations))
        annotations.extend(ruff_check.annotations)
        _write_report(report)
    else:
        results["ruff-check"] = {"outcome": "skipped", "violations": 0}

    ruff_format = ToolOutcome()
    if _truthy(_get("LINT_RUFF_FORMAT_ENABLED")):
        ruff_format, unformatted, diff, report = _run_ruff_format(
            working_directory, workspace, paths, ruff_version, sync_enabled
        )
        results["ruff-format"] = {"outcome": ruff_format.outcome, "unformatted-files": unformatted}
        summary_sections.append(_ruff_format_summary(ruff_format.outcome, unformatted, diff))
        annotations.extend(ruff_format.annotations)
        _write_report(report)
    else:
        results["ruff-format"] = {"outcome": "skipped", "unformatted-files": 0}

    tool = _get("LINT_TYPECHECK_TOOL") or "mypy"
    if _truthy(_get("LINT_TYPECHECK_ENABLED")):
        typecheck, runs, reports = _run_typecheck(working_directory, workspace, paths, sync_enabled)
        results["typecheck"] = {"outcome": typecheck.outcome, "tool": tool, "runs": runs}
        summary_sections.append(_typecheck_summary(typecheck.outcome, tool, runs))
        annotations.extend(typecheck.annotations)
        for report in reports:
            _write_report(report)
    else:
        typecheck = ToolOutcome()
        results["typecheck"] = {"outcome": "skipped", "tool": tool, "runs": []}

    overall = "failure" if _any_failure(results) else "success"
    document = {"version": 1, "tools": results}
    _write_report(("results.json", json.dumps(document, indent=2, sort_keys=True) + "\n"))
    _render_summary(overall, enforce, summary_sections)
    if annotations_enabled:
        _emit_annotations(annotations)
    _write_outputs(
        {
            "lint-outcome": overall,
            "ruff-check-outcome": str(results["ruff-check"]["outcome"]),
            "ruff-format-outcome": str(results["ruff-format"]["outcome"]),
            "typecheck-outcome": str(results["typecheck"]["outcome"]),
            "lint-results": json.dumps(document, sort_keys=True, separators=(",", ":")),
        }
    )

    crashed = ruff_check.crashed or ruff_format.crashed or typecheck.crashed
    if crashed:
        raise SystemExit(
            "A lint tool crashed (see the report); failing regardless of lint-enforce."
        )
    if enforce and overall == "failure":
        raise SystemExit("Lint findings reported and lint-enforce is true; failing the job.")
    return 0


# --------------------------------------------------------------------------- #
# tool runners                                                                 #
# --------------------------------------------------------------------------- #
def _run_ruff_check(
    working_directory: Path, workspace: Path, paths: list[str], version: str, sync: bool
) -> tuple[ToolOutcome, int, tuple[str, str]]:
    extra = _shlex("LINT_RUFF_CHECK_ARGUMENTS")
    command = _ruff_command(["check", "--output-format=json", *extra, *paths], version, sync)
    result = _run(command, working_directory)
    outcome, crashed = _classify(result.returncode)
    violations, annotations = _parse_ruff_check(result.stdout, workspace)
    return (
        ToolOutcome(outcome, crashed, annotations),
        violations,
        ("ruff-check.json", result.stdout),
    )


def _run_ruff_format(
    working_directory: Path, workspace: Path, paths: list[str], version: str, sync: bool
) -> tuple[ToolOutcome, int, str, tuple[str, str]]:
    extra = _shlex("LINT_RUFF_FORMAT_ARGUMENTS")
    command = _ruff_command(["format", "--check", "--diff", *extra, *paths], version, sync)
    result = _run(command, working_directory)
    outcome, crashed = _classify(result.returncode)
    unformatted = _parse_reformat_count(result.stdout + "\n" + result.stderr)
    annotations = _format_annotations(result.stdout, workspace, working_directory)
    return (
        ToolOutcome(outcome, crashed, annotations),
        unformatted,
        result.stdout,
        (
            "ruff-format.diff",
            result.stdout,
        ),
    )


def _run_typecheck(
    working_directory: Path, workspace: Path, paths: list[str], sync: bool
) -> tuple[ToolOutcome, list[dict[str, object]], list[tuple[str, str]]]:
    tool = _get("LINT_TYPECHECK_TOOL") or "mypy"
    version = _get("LINT_TYPECHECK_VERSION")
    extra = _shlex("LINT_TYPECHECK_ARGUMENTS")
    with_requirements = _split_lines(_get("LINT_TYPECHECK_WITH"))
    # typecheck-python-versions is a newline-separated list (convention), one checker
    # invocation per entry; empty runs a single invocation with the tool's default.
    target_versions = _split_lines(_get("LINT_TYPECHECK_PYTHON_VERSIONS")) or [None]

    outcome = "success"
    crashed = False
    annotations: list[dict[str, str]] = []
    runs: list[dict[str, object]] = []
    reports: list[tuple[str, str]] = []
    for target in target_versions:
        command = _typecheck_command(tool, version, target, extra, with_requirements, paths, sync)
        result = _run(command, working_directory)
        run_outcome, run_crashed = _classify(result.returncode)
        if run_outcome == "failure":
            outcome = "failure"
        crashed = crashed or run_crashed
        errors, run_annotations = _parse_typecheck(tool, result.stdout, result.stderr, workspace)
        annotations.extend(run_annotations)
        label = target or "default"
        runs.append({"python-version": label, "errors": errors})
        reports.append((f"typecheck-{label}.txt", result.stdout + result.stderr))
    return ToolOutcome(outcome, crashed, annotations), runs, reports


def _uv_sync(working_directory: Path) -> None:
    command = ["uv", "sync", *_shlex("LINT_UV_SYNC_ARGUMENTS")]
    result = _run(command, working_directory)
    if result.returncode != 0:
        _append_summary(f"## Python lint\n\n`uv sync` failed:\n\n```\n{result.stderr}\n```\n")
        raise SystemExit(f"uv sync failed with exit code {result.returncode}.")


# --------------------------------------------------------------------------- #
# command construction                                                         #
# --------------------------------------------------------------------------- #
def _ruff_command(arguments: list[str], version: str, sync: bool) -> list[str]:
    if sync and not version:
        # Use the project's pinned ruff from the synced environment.
        return ["uv", "run", "--no-sync", "ruff", *arguments]
    spec = f"ruff@{version}" if version else "ruff"
    return ["uvx", spec, *arguments]


def _typecheck_command(
    tool: str,
    version: str,
    target: str | None,
    extra: list[str],
    with_requirements: list[str],
    paths: list[str],
    sync: bool,
) -> list[str]:
    spec = _TYPECHECKERS[tool]
    command_name = str(spec["command"])
    argv = [str(part) for part in spec["argv"]]  # e.g. ["ty", "check"]; argv[0] == command_name
    version_flag = [str(spec["version_flag"]), target] if target else []
    tail = [*version_flag, *extra, *paths]
    if sync:
        base = ["uv", "run", "--no-sync"]
        base += ["--with", f"{command_name}=={version}" if version else command_name]
        for requirement in with_requirements:
            base += ["--with", requirement]
        return [*base, *argv, *tail]
    base = ["uvx"]
    for requirement in with_requirements:
        base += ["--with", requirement]
    # uvx runs the package's default entry point (argv[0] == command_name), so the
    # package spec carries the version and any subcommand follows as argv[1:].
    tool_spec = f"{command_name}@{version}" if version else command_name
    return [*base, tool_spec, *argv[1:], *tail]


# --------------------------------------------------------------------------- #
# result parsing                                                              #
# --------------------------------------------------------------------------- #
def _classify(returncode: int) -> tuple[str, bool]:
    if returncode == 0:
        return "success", False
    if returncode == 1:
        return "failure", False
    return "failure", True  # exit >= 2, a negative signal, or a launch failure: a crash


def _parse_ruff_check(stdout: str, workspace: Path) -> tuple[int, list[dict[str, str]]]:
    try:
        diagnostics = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError:
        return 0, []
    if not isinstance(diagnostics, list):
        return 0, []
    annotations: list[dict[str, str]] = []
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        location = item.get("location") or {}
        annotations.append(
            {
                "file": _relative(str(item.get("filename", "")), workspace),
                "line": str(location.get("row", 1)),
                "col": str(location.get("column", 1)),
                "title": f"ruff {item.get('code', '')}".strip(),
                "message": str(item.get("message", "")),
            }
        )
    return len(diagnostics), annotations


def _parse_reformat_count(text: str) -> int:
    match = _REFORMAT_COUNT.search(text)
    if match:
        return int(match.group(1))
    return sum(1 for line in text.splitlines() if line.startswith("--- "))


def _format_annotations(
    diff: str, workspace: Path, working_directory: Path
) -> list[dict[str, str]]:
    annotations: list[dict[str, str]] = []
    for line in diff.splitlines():
        if line.startswith("--- "):
            candidate = (working_directory / line[4:].strip()).resolve()
            annotations.append(
                {
                    "file": _relative(str(candidate), workspace),
                    "line": "1",
                    "col": "1",
                    "title": "ruff format",
                    "message": "File is not formatted; run `ruff format`.",
                }
            )
    return annotations


def _parse_typecheck(
    tool: str, stdout: str, stderr: str, workspace: Path
) -> tuple[int, list[dict[str, str]]]:
    text = stdout + "\n" + stderr
    pattern = _PYRIGHT_ERROR if tool == "pyright" else _MYPY_ERROR
    annotations: list[dict[str, str]] = []
    for match in pattern.finditer(text):
        annotations.append(
            {
                "file": _relative(match.group("file").strip(), workspace),
                "line": match.group("line"),
                "col": match.groupdict().get("col") or "1",
                "title": f"{tool} error",
                "message": f"{tool} reported a type error.",
            }
        )
    errors = len(annotations)
    if tool == "ty" and errors == 0:
        # ty's diagnostic layout differs; fall back to counting error headers.
        errors = sum(1 for line in text.splitlines() if line.startswith("error"))
    return errors, annotations


# --------------------------------------------------------------------------- #
# reporting                                                                    #
# --------------------------------------------------------------------------- #
def _ruff_check_summary(outcome: str, violations: int) -> str:
    return f"### ruff check: {outcome}\n\n{violations} violation(s).\n"


def _ruff_format_summary(outcome: str, unformatted: int, diff: str) -> str:
    lines = [f"### ruff format: {outcome}\n", f"{unformatted} unformatted file(s)."]
    if diff.strip():
        capped = diff[:_SUMMARY_DIFF_CAP]
        if len(diff) > _SUMMARY_DIFF_CAP:
            capped += "\n... (diff truncated)"
        lines.append(f"\n```diff\n{capped}\n```")
    return "\n".join(lines) + "\n"


def _typecheck_summary(outcome: str, tool: str, runs: list[dict[str, object]]) -> str:
    rows = "\n".join(f"- {run['python-version']}: {run['errors']} error(s)" for run in runs)
    return f"### typecheck ({tool}): {outcome}\n\n{rows}\n"


def _render_summary(overall: str, enforce: bool, sections: list[str]) -> None:
    mode = "enforcing" if enforce else "advisory (report-only)"
    header = f"## Python lint results\n\nOverall: **{overall}** ({mode})\n\n"
    _append_summary(header + "\n".join(sections))


def _emit_annotations(annotations: list[dict[str, str]]) -> None:
    per_tool: dict[str, int] = {}
    for annotation in annotations:
        title = annotation["title"]
        per_tool[title] = per_tool.get(title, 0) + 1
        if per_tool[title] > _ANNOTATION_CAP:
            continue
        file = _escape_property(annotation["file"])
        title_value = _escape_property(annotation["title"])
        message = _escape_data(annotation["message"])
        print(
            f"::error file={file},line={annotation['line']},"
            f"col={annotation['col']},title={title_value}::{message}"
        )


def _write_report(report: tuple[str, str]) -> None:
    directory = _get("LINT_REPORT_DIRECTORY")
    if not directory:
        return
    name, content = report
    base = (Path(os.environ["GITHUB_WORKSPACE"]) / directory).resolve()
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_text(content, encoding="utf-8")


def _write_outputs(outputs: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            if "\n" in value:
                raise SystemExit(f"output {key} must not contain a newline.")
            handle.write(f"{key}={value}\n")


def _append_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _run(command: list[str], cwd: Path) -> RunResult:
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        return RunResult(127, "", str(error))
    return RunResult(completed.returncode, completed.stdout, completed.stderr)


def _any_failure(results: dict[str, dict[str, object]]) -> bool:
    return any(tool.get("outcome") == "failure" for tool in results.values())


def _relative(path: str, workspace: Path) -> str:
    if not path:
        return path
    try:
        return os.path.relpath(Path(path).resolve(), workspace)
    except ValueError:
        return path


def _escape_property(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _shlex(env_name: str) -> list[str]:
    value = _get(env_name)
    return shlex.split(value) if value else []


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _get(name: str) -> str:
    return os.environ.get(name, "").strip()


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
