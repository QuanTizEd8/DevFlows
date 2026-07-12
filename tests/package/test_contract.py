"""Adapter contract test for the pinned actions the generator emits.

This is a network test (marked ``network``) and is excluded from the default run.
CI runs it whenever an action pin changes, via ``pytest -m network``. For every
pinned action the generator injects a ``with:`` block for, it fetches that action's
action.yml at the pinned SHA and asserts every emitted input key really exists.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest
import yaml

from devflows.actions import PINS_BY_REF
from devflows.catalog import load_catalog
from devflows.publish import build_published_workflow

pytestmark = pytest.mark.network


def _emitted_with_keys() -> dict[str, set[str]]:
    emitted: dict[str, set[str]] = {}
    for item in load_catalog():
        workflow = build_published_workflow(item)
        for job in workflow.get("jobs", {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps", []) or []:
                uses = step.get("uses")
                with_block = step.get("with")
                if uses in PINS_BY_REF and isinstance(with_block, dict):
                    emitted.setdefault(uses, set()).update(with_block.keys())
    return emitted


def _fetch_action_inputs(action: str, sha: str) -> set[str]:
    last_error: Exception | None = None
    for filename in ("action.yml", "action.yaml"):
        url = f"https://raw.githubusercontent.com/{action}/{sha}/{filename}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
                data = yaml.safe_load(response.read())
            return set((data or {}).get("inputs", {}) or {})
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code == 404:
                continue
            raise
        except urllib.error.URLError as error:  # pragma: no cover - network dependent
            pytest.skip(f"network unavailable fetching {url}: {error}")
    raise AssertionError(f"could not fetch action.yml for {action}@{sha}: {last_error}")


def test_emitted_with_keys_exist_in_action_inputs() -> None:
    emitted = _emitted_with_keys()
    assert emitted, "expected the generator to emit at least one pinned-action with block"
    for uses, keys in sorted(emitted.items()):
        action, sha = uses.split("@", 1)
        inputs = _fetch_action_inputs(action, sha)
        missing = keys - inputs
        assert not missing, f"{uses} does not accept generated inputs: {sorted(missing)}"
