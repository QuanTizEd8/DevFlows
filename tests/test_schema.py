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
