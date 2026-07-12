"""Permission checks on the catalog's published example fixtures.

Every workflow's ``examples`` in its devflow.yaml is a real call site embedded
verbatim into the generated reference docs. A job that calls a catalog reusable
workflow must grant at least the union of that workflow's declared permission tree
(job-level blocks replace the workflow-level grant), or GitHub fails the
nested-permission check at startup. This mirrors
``test_internal_callers_grant_required_permissions`` but scans the example
fixtures rather than the repo's own internal workflows -- the check that would
have caught the doubly-broken pages-chain example.
"""

from __future__ import annotations

import re
from pathlib import Path

from devflows.catalog import load_catalog
from devflows.scenarios import _required_call_permissions
from devflows.yaml import load_yaml

_RANK = {"none": 0, "read": 1, "write": 2}
# Extract the reusable-workflow id from a job `uses:`, in either the full
# owner/repo form (…/.github/workflows/<id>.yaml@<id>/vX.Y.Z) or the relative
# ./.github/workflows/<id>.yaml form.
_WORKFLOW_USES = re.compile(r"\.github/workflows/(?P<id>[a-z0-9-]+)\.yaml(?:@|$)")


def test_example_fixtures_grant_required_permissions() -> None:
    catalog = {item.id: item for item in load_catalog()}
    checked = 0
    for item in catalog.values():
        for example in item.metadata.get("examples") or []:
            path = Path(str(example.get("path") or ""))
            assert path.is_file(), f"{item.id} example fixture missing: {path}"
            workflow = load_yaml(path)
            top = workflow.get("permissions")
            top_perms = top if isinstance(top, dict) else {}
            for job_id, job in (workflow.get("jobs") or {}).items():
                if not isinstance(job, dict):
                    continue
                match = _WORKFLOW_USES.search(str(job.get("uses") or ""))
                if not match or match.group("id") not in catalog:
                    continue
                required = _required_call_permissions(catalog[match.group("id")])
                # Job-level permissions replace the workflow-level grant; fall back
                # to the workflow level only when the job declares none.
                job_perms = job.get("permissions")
                effective = job_perms if isinstance(job_perms, dict) else top_perms
                for name, level in required.items():
                    granted = str(effective.get(name, "none"))
                    assert _RANK.get(granted, 0) >= _RANK[level], (
                        f"{path}:{job_id} calls {match.group('id')} which needs "
                        f"{name}: {level}, but grants {name}: {granted}"
                    )
                checked += 1
    assert checked > 0, "expected at least one example fixture calling a catalog workflow"
