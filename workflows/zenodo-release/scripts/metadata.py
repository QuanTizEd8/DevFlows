"""Metadata guards shared by validate-inputs.py and prepare.py.

Owned-key rejection for the zenodo-metadata-extra escape hatch, its JSON-object
validation, and the required-field completeness check. CITATION.cff parsing and the
full build live in cff.py (prepare only).
"""

from __future__ import annotations

import json

# Keys DevFlows owns or derives; a caller must not smuggle them through
# zenodo-metadata-extra (mirrors the owned-flag rejection on -arguments inputs).
OWNED_METADATA_KEYS = frozenset(
    {
        "doi",
        "prereserve_doi",
        "conceptdoi",
        "conceptrecid",
        "title",
        "creators",
        "description",
        "upload_type",
        "version",
        "license",
        "keywords",
    }
)


class MetadataError(ValueError):
    """A metadata input failed validation."""


def validate_metadata_extra(raw: str) -> dict[str, object]:
    """Parse zenodo-metadata-extra as a JSON object and reject owned keys."""
    raw = raw.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MetadataError(f"zenodo-metadata-extra is not valid JSON: {error}.") from error
    if not isinstance(data, dict):
        raise MetadataError("zenodo-metadata-extra must be a JSON object.")
    owned = sorted(key for key in data if key in OWNED_METADATA_KEYS)
    if owned:
        raise MetadataError(
            "zenodo-metadata-extra may not carry DevFlows-owned/derived keys "
            f"({', '.join(owned)}); set them through the typed zenodo-* inputs."
        )
    return data


def require_metadata_complete(*, title: str, creators: str, description: str) -> None:
    """Fail when required metadata is absent and no CITATION.cff supplies it."""
    missing = [
        field
        for field, value in (
            ("zenodo-title", title),
            ("zenodo-creators", creators),
            ("zenodo-description", description),
        )
        if not value.strip()
    ]
    if missing:
        raise MetadataError(
            "zenodo-enabled needs deposition metadata: provide "
            "zenodo-metadata-cff-path, or set " + ", ".join(missing) + "."
        )
