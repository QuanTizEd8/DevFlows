from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from devflows.catalog import Workflow

SCHEMA_RESOURCE = "devflow.schema.json"


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    text = (
        resources.files("devflows").joinpath("schemas", SCHEMA_RESOURCE).read_text(encoding="utf-8")
    )
    return json.loads(text)


def schema_errors(item: Workflow) -> list[str]:
    """Validate a workflow's devflow.yaml against the JSON Schema.

    Returns clear, path-qualified messages (no tracebacks). Unknown keys are
    rejected because every object in the schema sets additionalProperties: false.
    """
    import jsonschema

    validator = jsonschema.Draft202012Validator(load_schema())
    messages: list[str] = []
    errors = sorted(validator.iter_errors(item.metadata), key=lambda err: list(err.absolute_path))
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{item.metadata_path}: {location}: {error.message}")
    return messages
