from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "workflows" / "_channels" / "scripts" / "collect-job-outputs.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("collect_job_outputs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = _load()


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mapping: str, **env: str) -> dict:
    """Run the collector in ``tmp_path`` and return the parsed job-outputs object."""
    output = tmp_path / "github_output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEVFLOWS_JOB_OUTPUT_MAP", mapping)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert collect.main() == 0
    return _parse(output.read_text(encoding="utf-8"))


def _parse(rendered: str) -> dict:
    """Parse the single ``job-outputs<<DELIM ... DELIM`` heredoc entry."""
    lines = rendered.splitlines()
    assert lines[0].startswith("job-outputs<<"), rendered
    delimiter = lines[0].split("<<", 1)[1]
    # Exactly one entry: an opening line, the JSON body lines, and one closing delimiter.
    assert lines.count(delimiter) == 1, "collector must emit exactly one closing delimiter"
    body = "\n".join(lines[1 : lines.index(delimiter, 1)])
    return json.loads(body)


def test_env_and_file_sources_resolve(tmp_path, monkeypatch) -> None:
    (tmp_path / "note.txt").write_text("file body\n", encoding="utf-8")
    result = _run(
        tmp_path,
        monkeypatch,
        "# a comment\n\nver=env:MYVER\nbody=file:note.txt",
        MYVER="1.2.3",
    )

    assert result == {"ver": "1.2.3", "body": "file body\n"}


def test_missing_env_and_file_resolve_to_empty_string(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ABSENT", raising=False)
    result = _run(tmp_path, monkeypatch, "a=env:ABSENT\nb=file:does-not-exist.txt")

    assert result == {"a": "", "b": ""}


def test_multiline_file_content_stays_one_output_entry(tmp_path, monkeypatch) -> None:
    (tmp_path / "multi.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    result = _run(tmp_path, monkeypatch, "m=file:multi.txt")

    assert result == {"m": "one\ntwo\nthree\n"}


@pytest.mark.parametrize("source", ["notasource", "http:not", "value-with-no-scheme"])
def test_bad_source_is_rejected_naming_only_the_key(tmp_path, monkeypatch, source) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEVFLOWS_JOB_OUTPUT_MAP", f"secretish={source}")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    with pytest.raises(SystemExit) as excinfo:
        collect.main()
    message = str(excinfo.value)
    assert "secretish" in message
    assert source not in message  # never echo the source/value, only the key


@pytest.mark.parametrize("path", ["/etc/passwd", "../escape", "sub/../../escape"])
def test_absolute_and_traversal_file_paths_are_rejected(tmp_path, monkeypatch, path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEVFLOWS_JOB_OUTPUT_MAP", f"k=file:{path}")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    with pytest.raises(SystemExit) as excinfo:
        collect.main()
    assert "workspace-relative" in str(excinfo.value)


def test_malformed_key_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEVFLOWS_JOB_OUTPUT_MAP", "not a valid key=env:X")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    with pytest.raises(SystemExit):
        collect.main()


def test_crafted_value_cannot_inject_extra_output_line(tmp_path, monkeypatch) -> None:
    # A file whose content forges a GITHUB_OUTPUT heredoc must not smuggle a second
    # output: JSON-encoding collapses the newlines and the random delimiter is
    # unguessable, so the collector still emits exactly one job-outputs entry.
    (tmp_path / "evil.txt").write_text("x\nmalicious<<END\ninjected=pwned\nEND\n", encoding="utf-8")
    output = tmp_path / "github_output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEVFLOWS_JOB_OUTPUT_MAP", "k=file:evil.txt")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert collect.main() == 0

    rendered = output.read_text(encoding="utf-8")
    # The whole entry is exactly three lines -- opener, single JSON payload line,
    # closer -- because JSON-encoding collapsed every newline in the value. No forged
    # heredoc line survives as its own output.
    assert len(rendered.splitlines()) == 3
    assert rendered.splitlines()[0].startswith("job-outputs<<")
    assert _parse(rendered) == {"k": "x\nmalicious<<END\ninjected=pwned\nEND\n"}


def test_missing_github_output_is_an_error(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEVFLOWS_JOB_OUTPUT_MAP", "k=env:X")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("X", "y")
    with pytest.raises(SystemExit):
        collect.main()


def test_empty_map_writes_empty_object(tmp_path, monkeypatch) -> None:
    assert _run(tmp_path, monkeypatch, "\n# only comments\n") == {}
