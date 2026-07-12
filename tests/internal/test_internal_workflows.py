"""Consistency checks on the repository's own internal workflows.

These scan the committed ``.github/workflows/_*.yaml`` files (hand-written
and generated) rather than the catalog, guarding two startup-failure classes:

* item 1/2: an internal job that calls a catalog reusable workflow must grant at
  least the union of that workflow's declared permission tree, or GitHub fails
  the nested-permission check at startup.
* item 20: an internal workflow that pins a registry-known action must pin the
  same SHA the generator emits, so they never drift a release apart.
"""

from __future__ import annotations

import re
from pathlib import Path

from devflows.actions import ACTION_PINS
from devflows.catalog import load_catalog
from devflows.scenarios import _required_call_permissions
from devflows.yaml import load_yaml

PUBLISHED_DIR = Path(".github/workflows")
_RANK = {"none": 0, "read": 1, "write": 2}
_INTERNAL_CALL = re.compile(r"^\./\.github/workflows/(?P<id>[a-z0-9-]+)\.yaml$")
_USES_PIN = re.compile(r"^(?P<ref>[^@\s]+@[0-9a-f]{40})")


def _internal_workflows() -> list[Path]:
    return sorted(PUBLISHED_DIR.glob("_*.yaml"))


def test_internal_callers_grant_required_permissions() -> None:
    catalog = {item.id: item for item in load_catalog()}
    checked = 0
    for path in _internal_workflows():
        workflow = load_yaml(path)
        top = workflow.get("permissions")
        top_perms = top if isinstance(top, dict) else {}
        for job_id, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            match = _INTERNAL_CALL.match(str(job.get("uses") or ""))
            if not match or match.group("id") not in catalog:
                continue
            required = _required_call_permissions(catalog[match.group("id")])
            # Job-level permissions replace the workflow-level grant; fall back to
            # the workflow level only when the job declares none.
            job_perms = job.get("permissions")
            effective = job_perms if isinstance(job_perms, dict) else top_perms
            for name, level in required.items():
                granted = str(effective.get(name, "none"))
                assert _RANK.get(granted, 0) >= _RANK[level], (
                    f"{path.name}:{job_id} calls {match.group('id')} which needs "
                    f"{name}: {level}, but grants {name}: {granted}"
                )
            checked += 1
    assert checked > 0, "expected at least one internal caller of a catalog workflow"


def test_devflows_docs_deploys_via_deploy_pages_call() -> None:
    """_docs dogfoods the catalog: its deploy job calls deploy-pages and
    grants the full permission union that reusable workflow's job tree declares."""
    catalog = {item.id: item for item in load_catalog()}
    workflow = load_yaml(PUBLISHED_DIR / "_docs.yaml")
    deploy = (workflow.get("jobs") or {}).get("deploy")
    assert isinstance(deploy, dict), "_docs.yaml must have a deploy job"
    assert deploy.get("uses") == "./.github/workflows/deploy-pages.yaml"
    required = _required_call_permissions(catalog["deploy-pages"])
    # The union deploy-pages declares (actions: read, contents: read,
    # id-token: write, pages: write) must be granted, or the nested call
    # startup-fails.
    assert required == {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
        "pages": "write",
    }
    granted = deploy.get("permissions")
    assert isinstance(granted, dict), "the deploy job must declare permissions"
    for name, level in required.items():
        assert _RANK.get(str(granted.get(name, "none")), 0) >= _RANK[level], (
            f"deploy job grants {name}: {granted.get(name, 'none')}, needs {level}"
        )


def test_internal_workflow_pins_match_registry() -> None:
    known = {pin.action: pin for pin in ACTION_PINS.values()}
    checked = 0
    for path in _internal_workflows():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("uses:"):
                continue
            match = _USES_PIN.match(line[len("uses:") :].strip())
            if not match:
                continue
            action, sha = match.group("ref").split("@", 1)
            pin = known.get(action)
            if pin is None:
                continue
            assert sha == pin.sha, (
                f"{path.name} pins {action}@{sha}, but the registry pins "
                f"{pin.sha} ({pin.version}); align them (item 20)."
            )
            checked += 1
    assert checked > 0, "expected at least one registry-known pin in internal workflows"
