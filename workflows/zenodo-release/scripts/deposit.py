"""Zenodo deposition driver for the credentialed zenodo-deposit job.

Consumes the resolved deposition-metadata JSON and asset list from prepare (this
job never checks out), then drives the Zenodo REST API via the DevFlows-owned
zenodo_api client: create a new deposition or a new version of a concept record,
PUT metadata, reserve the DOI, replace or keep inherited files, upload the assets
to the bucket, and POST publish ONLY when zenodo-publish-enabled. ZENODO_TOKEN is
read from the environment on this single step; the real requests.Session is built
only in main(), so the request logic is unit-tested against a fake session.
"""

from __future__ import annotations

import json
import os
import secrets as _secrets
from pathlib import Path
from typing import Any

import zenodo_api


def run_deposit(
    client: zenodo_api.ZenodoClient,
    metadata: dict[str, Any],
    asset_paths: list[Path],
    *,
    concept_doi: str,
    file_mode: str,
    publish: bool,
    sandbox: bool,
) -> dict[str, str]:
    """Create/update a deposition, upload assets, optionally publish; return outputs."""
    if concept_doi.strip():
        recid = zenodo_api.concept_recid(concept_doi)
        deposition = client.new_version_draft(recid)
        deposition = client.update_metadata(deposition["id"], metadata)
    else:
        deposition = client.create_deposition(metadata)

    dep_id = deposition["id"]
    links = deposition.get("links") or {}
    bucket = str(links.get("bucket") or "")
    if not bucket:
        raise zenodo_api.ZenodoApiError(f"deposition {dep_id} exposed no upload bucket.")

    if concept_doi.strip() and file_mode == "replace":
        for existing in client.list_files(dep_id):
            client.delete_file(dep_id, existing.get("id"))

    for path in asset_paths:
        client.upload_file(bucket, path.name, path)

    state = "draft"
    if publish:
        client.publish(dep_id)
        deposition = client.get(f"/deposit/depositions/{dep_id}")
        state = "published"

    return _outputs(deposition, dep_id=dep_id, state=state, sandbox=sandbox)


def _outputs(
    deposition: dict[str, Any], *, dep_id: Any, state: str, sandbox: bool
) -> dict[str, str]:
    meta = deposition.get("metadata") or {}
    reserved = meta.get("prereserve_doi") or {}
    doi = str(deposition.get("doi") or reserved.get("doi") or "")
    concept = str(deposition.get("conceptdoi") or "")
    links = deposition.get("links") or {}
    record_url = str(links.get("html") or links.get("record_html") or "")
    if not record_url:
        record_url = f"{zenodo_api.record_html_base(sandbox=sandbox)}/records/{dep_id}"
    return {
        "zenodo-doi": doi,
        "zenodo-concept-doi": concept,
        "zenodo-record-url": record_url,
        "zenodo-deposition-id": str(dep_id),
        "zenodo-state": state,
    }


def main() -> int:
    if _bool("PUBLISH_DRY_RUN_ENABLED"):
        print("publish-dry-run-enabled: zenodo-deposit makes no API calls.")
        return 0

    token = os.environ.get("ZENODO_TOKEN", "")
    if not token:
        raise SystemExit("ZENODO_TOKEN is empty; the credential preflight should have caught this.")
    metadata = json.loads(os.environ["DEPOSITION_METADATA"])
    asset_paths = [
        Path(line.strip())
        for line in os.environ.get("ZENODO_ASSET_LIST", "").splitlines()
        if line.strip()
    ]
    sandbox = _bool("ZENODO_SANDBOX_ENABLED")

    import requests  # local import: real session only at run time.

    client = zenodo_api.ZenodoClient(
        requests.Session(), base=zenodo_api.base_url(sandbox=sandbox), token=token
    )
    outputs = run_deposit(
        client,
        metadata,
        asset_paths,
        concept_doi=os.environ.get("ZENODO_CONCEPT_DOI", ""),
        file_mode=os.environ.get("ZENODO_NEW_VERSION_FILE_MODE", "replace").strip() or "replace",
        publish=_bool("ZENODO_PUBLISH_ENABLED"),
        sandbox=sandbox,
    )
    _emit_outputs(outputs)
    print(
        f"zenodo-release: deposition {outputs['zenodo-deposition-id']} ({outputs['zenodo-state']})."
    )
    return 0


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _emit_outputs(outputs: dict[str, str]) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            delimiter = f"ghadelim_{_secrets.token_hex(16)}"
            handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


if __name__ == "__main__":
    raise SystemExit(main())
