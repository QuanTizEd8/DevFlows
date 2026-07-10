"""Minimal DevFlows-owned client for the Zenodo REST deposition API.

Drives the Zenodo REST API directly (developers.zenodo.org): create a deposition
or a new version of a concept record, PUT metadata, read the reserved DOI, upload
files to the deposition bucket, and POST the publish action. NO third-party action
holds the token; the client is imported only by deposit.py in the credentialed
zenodo-deposit job.

The HTTP session is dependency-injected (any object exposing get/post/put/delete
returning objects with status_code/json()/text), so unit tests exercise the full
request logic against a fake session without a network or a real requests install.
Only deposit.py's main() constructs a real requests.Session at run time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PRODUCTION_BASE = "https://zenodo.org/api"
SANDBOX_BASE = "https://sandbox.zenodo.org/api"


def base_url(*, sandbox: bool) -> str:
    return SANDBOX_BASE if sandbox else PRODUCTION_BASE


def record_html_base(*, sandbox: bool) -> str:
    return "https://sandbox.zenodo.org" if sandbox else "https://zenodo.org"


class ZenodoApiError(RuntimeError):
    """A Zenodo API request returned an error status."""


def concept_recid(concept_doi: str) -> str:
    """Extract the numeric record id from a Zenodo concept DOI or bare recid."""
    value = concept_doi.strip()
    if not value:
        raise ZenodoApiError("zenodo-concept-doi is empty.")
    tail = value.rsplit("zenodo.", 1)[-1] if "zenodo." in value else value
    tail = tail.strip().strip("/")
    if not tail.isdigit():
        raise ZenodoApiError(
            f"could not parse a Zenodo record id from zenodo-concept-doi {concept_doi!r}."
        )
    return tail


class ZenodoClient:
    """A thin wrapper over the Zenodo deposition REST endpoints."""

    def __init__(self, session: Any, *, base: str, token: str) -> None:
        self._session = session
        self._base = base.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    # -- low-level ---------------------------------------------------------
    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self._base}{path}"

    def _json(self, response: Any, *, ok: tuple[int, ...]) -> dict[str, Any]:
        if response.status_code not in ok:
            raise ZenodoApiError(
                f"Zenodo API returned HTTP {response.status_code}: {_body(response)}"
            )
        try:
            return dict(response.json())
        except ValueError as error:
            raise ZenodoApiError(f"Zenodo API response was not JSON: {error}.") from error

    def get(self, path: str) -> dict[str, Any]:
        response = self._session.get(self._url(path), headers=self._headers)
        return self._json(response, ok=(200,))

    # -- deposition lifecycle ---------------------------------------------
    def create_deposition(self, metadata: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(
            self._url("/deposit/depositions"),
            headers=self._headers,
            json={"metadata": metadata},
        )
        return self._json(response, ok=(200, 201))

    def new_version_draft(self, recid: str) -> dict[str, Any]:
        """Open a new-version draft of a concept's latest record; return the draft."""
        response = self._session.post(
            self._url(f"/deposit/depositions/{recid}/actions/newversion"),
            headers=self._headers,
        )
        parent = self._json(response, ok=(201, 200))
        draft_url = ((parent.get("links") or {}).get("latest_draft")) or ""
        if not draft_url:
            raise ZenodoApiError(f"newversion on record {recid} returned no links.latest_draft.")
        return self.get(draft_url)

    def update_metadata(self, dep_id: Any, metadata: dict[str, Any]) -> dict[str, Any]:
        response = self._session.put(
            self._url(f"/deposit/depositions/{dep_id}"),
            headers=self._headers,
            json={"metadata": metadata},
        )
        return self._json(response, ok=(200,))

    def list_files(self, dep_id: Any) -> list[dict[str, Any]]:
        response = self._session.get(
            self._url(f"/deposit/depositions/{dep_id}/files"), headers=self._headers
        )
        if response.status_code not in (200,):
            raise ZenodoApiError(f"listing files for deposition {dep_id} failed: {_body(response)}")
        return list(response.json())

    def delete_file(self, dep_id: Any, file_id: Any) -> None:
        response = self._session.delete(
            self._url(f"/deposit/depositions/{dep_id}/files/{file_id}"),
            headers=self._headers,
        )
        if response.status_code not in (204, 200):
            raise ZenodoApiError(
                f"deleting file {file_id} on deposition {dep_id} failed: {_body(response)}"
            )

    def upload_file(self, bucket_url: str, name: str, path: Path) -> None:
        with path.open("rb") as handle:
            response = self._session.put(
                f"{bucket_url.rstrip('/')}/{name}", headers=self._headers, data=handle
            )
        if response.status_code not in (200, 201):
            raise ZenodoApiError(f"uploading {name} failed: {_body(response)}")

    def publish(self, dep_id: Any) -> dict[str, Any]:
        response = self._session.post(
            self._url(f"/deposit/depositions/{dep_id}/actions/publish"),
            headers=self._headers,
        )
        return self._json(response, ok=(200, 202))


def _body(response: Any) -> str:
    try:
        return str(response.text)[:500]
    except Exception:  # pragma: no cover - defensive
        return "<no body>"
