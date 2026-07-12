from __future__ import annotations

from devflows.catalog import load_catalog, load_workflow
from devflows.schema import schema_errors

_DEVFLOW_WITH_UNKNOWN_KEY = """\
id: demo
name: Demo
sumary: misspelled summary field
status: active
release:
  type: simple
  major: 1
"""

_DEVFLOW_WITH_BAD_STATUS = """\
id: demo
name: Demo
status: retired
release:
  type: simple
  major: 1
"""


def test_active_catalog_passes_schema() -> None:
    for item in load_catalog():
        assert schema_errors(item) == []


def test_schema_rejects_unknown_top_level_key(make_catalog) -> None:
    root = make_catalog(devflow_yaml=_DEVFLOW_WITH_UNKNOWN_KEY)
    item = load_workflow(root / "workflows/demo")

    errors = schema_errors(item)

    assert errors
    assert any("sumary" in message for message in errors)
    assert all(str(item.metadata_path) in message for message in errors)


def test_schema_rejects_invalid_enum(make_catalog) -> None:
    root = make_catalog(devflow_yaml=_DEVFLOW_WITH_BAD_STATUS)
    item = load_workflow(root / "workflows/demo")

    errors = schema_errors(item)

    assert any("status" in message for message in errors)


def _validate_metadata(doc: dict) -> list:
    import jsonschema

    from devflows.schema import load_schema

    return list(jsonschema.Draft202012Validator(load_schema()).iter_errors(doc))


_BASE_METADATA = {
    "id": "demo",
    "name": "Demo",
    "status": "active",
    "release": {"type": "simple", "major": 1},
}


def test_schema_accepts_validation_failure_scenario_without_assertions() -> None:
    doc = {
        **_BASE_METADATA,
        "tests": {
            "scenarios": [
                {
                    "id": "boom",
                    "runs": ["local", "hosted"],
                    "expect": "validation-failure",
                    "failure-message-contains": "must be a nonempty",
                }
            ]
        },
    }

    assert _validate_metadata(doc) == []


def test_schema_rejects_unknown_expect_value() -> None:
    doc = {
        **_BASE_METADATA,
        "tests": {"scenarios": [{"id": "boom", "runs": ["hosted"], "expect": "maybe"}]},
    }

    assert _validate_metadata(doc)


def test_schema_rejects_removed_expect_failure_value() -> None:
    # The old call-level `expect: failure` (continue-on-error) shape is gone.
    doc = {
        **_BASE_METADATA,
        "tests": {"scenarios": [{"id": "boom", "runs": ["hosted"], "expect": "failure"}]},
    }

    assert _validate_metadata(doc)


def test_schema_setup_file_rejects_multiple_sources() -> None:
    doc = {
        **_BASE_METADATA,
        "tests": {
            "scenarios": [
                {
                    "id": "s",
                    "runs": ["hosted"],
                    "assertions": [{"type": "workflow-output-equals", "name": "o", "value": "v"}],
                    "setup-artifact": {
                        "name": "n",
                        "path": "p",
                        "files": [{"path": "a", "content": "x", "source-path": "b"}],
                    },
                }
            ]
        },
    }

    assert _validate_metadata(doc)


def test_schema_setup_file_accepts_source_path() -> None:
    doc = {
        **_BASE_METADATA,
        "tests": {
            "scenarios": [
                {
                    "id": "s",
                    "runs": ["hosted"],
                    "assertions": [{"type": "workflow-output-equals", "name": "o", "value": "v"}],
                    "setup-artifact": {
                        "name": "n",
                        "path": "p",
                        "files": [{"path": "a", "source-path": "tests/x/pkg.whl"}],
                    },
                }
            ]
        },
    }

    assert _validate_metadata(doc) == []
