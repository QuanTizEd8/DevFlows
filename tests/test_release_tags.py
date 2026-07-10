from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "move_major_tags.py"
_spec = importlib.util.spec_from_file_location("move_major_tags", _SCRIPT)
assert _spec and _spec.loader
move_major_tags = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(move_major_tags)

compute_major_tag_moves = move_major_tags.compute_major_tag_moves


def _release(path: str, tag: str, sha: str, major: str) -> dict:
    return {
        f"{path}--tag_name": tag,
        f"{path}--sha": sha,
        f"{path}--major": major,
    }


def test_no_releases_created() -> None:
    assert compute_major_tag_moves({"releases_created": "false"}) == []


def test_zero_x_release_is_dormant() -> None:
    outputs = {
        "releases_created": "true",
        "paths_released": '["workflows/pandoc"]',
        **_release("workflows/pandoc", "pandoc/v0.2.0", "abc123", "0"),
    }
    assert compute_major_tag_moves(outputs) == []


def test_major_release_moves_tag() -> None:
    outputs = {
        "releases_created": "true",
        "paths_released": '["workflows/pandoc"]',
        **_release("workflows/pandoc", "pandoc/v1.4.2", "deadbeef", "1"),
    }
    assert compute_major_tag_moves(outputs) == [("pandoc/v1", "deadbeef")]


def test_mixed_paths_only_major_ge_1() -> None:
    outputs = {
        "releases_created": "true",
        "paths_released": '["workflows/pandoc", "workflows/writeback"]',
        **_release("workflows/pandoc", "pandoc/v2.0.0", "sha-pandoc", "2"),
        **_release("workflows/writeback", "writeback/v0.5.0", "sha-wb", "0"),
    }
    assert compute_major_tag_moves(outputs) == [("pandoc/v2", "sha-pandoc")]


def test_hyphenated_component_name() -> None:
    outputs = {
        "releases_created": "true",
        "paths_released": '["workflows/build-devcontainer"]',
        **_release("workflows/build-devcontainer", "build-devcontainer/v1.0.0", "sha-bd", "1"),
    }
    assert compute_major_tag_moves(outputs) == [("build-devcontainer/v1", "sha-bd")]


def test_incomplete_outputs_are_skipped() -> None:
    outputs = {
        "releases_created": "true",
        "paths_released": '["workflows/pandoc"]',
        "workflows/pandoc--tag_name": "pandoc/v1.0.0",
        "workflows/pandoc--major": "1",
        # missing sha
    }
    assert compute_major_tag_moves(outputs) == []


def test_malformed_paths_released() -> None:
    outputs = {"releases_created": "true", "paths_released": "not json"}
    assert compute_major_tag_moves(outputs) == []
