"""CITATION.cff parsing and Zenodo deposition-metadata assembly (prepare only).

Runs in the credential-free prepare job (which alone has checkout). Explicit
zenodo-* inputs always override CFF-derived values. Imported by prepare.py; never
inlined into the credentialed jobs, which consume the resolved metadata JSON.
Requires PyYAML at run time (prepare installs it ephemerally via uv).
"""

from __future__ import annotations

from pathlib import Path

import yaml


class CffError(ValueError):
    """A CITATION.cff or metadata input could not be parsed."""


def load_cff(path: Path) -> dict[str, object]:
    """Parse a CITATION.cff file into a mapping (empty mapping when absent)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CffError(f"could not read zenodo-metadata-cff-path {path}: {error}.") from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise CffError(f"CITATION.cff is not valid YAML: {error}.") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise CffError("CITATION.cff must be a YAML mapping.")
    return data


def _strip_orcid(value: str) -> str:
    value = value.strip()
    for prefix in ("https://orcid.org/", "http://orcid.org/", "orcid.org/"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def cff_creators(cff: dict[str, object]) -> list[dict[str, str]]:
    """Convert CITATION.cff authors into Zenodo creator objects."""
    authors = cff.get("authors")
    creators: list[dict[str, str]] = []
    if not isinstance(authors, list):
        return creators
    for author in authors:
        if not isinstance(author, dict):
            continue
        family = str(author.get("family-names") or "").strip()
        given = str(author.get("given-names") or "").strip()
        entity = str(author.get("name") or "").strip()
        if family and given:
            name = f"{family}, {given}"
        elif family:
            name = family
        elif entity:
            name = entity
        else:
            continue
        creator: dict[str, str] = {"name": name}
        affiliation = str(author.get("affiliation") or "").strip()
        if affiliation:
            creator["affiliation"] = affiliation
        orcid = _strip_orcid(str(author.get("orcid") or ""))
        if orcid:
            creator["orcid"] = orcid
        creators.append(creator)
    return creators


def parse_creators(raw: str) -> list[dict[str, str]]:
    """Parse newline creators 'Family, Given | Affiliation | ORCID' into objects."""
    creators: list[dict[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [segment.strip() for segment in line.split("|")]
        name = parts[0]
        if not name:
            raise CffError(f"zenodo-creators line has an empty name: {line!r}.")
        creator: dict[str, str] = {"name": name}
        if len(parts) >= 2 and parts[1]:
            creator["affiliation"] = parts[1]
        if len(parts) >= 3 and parts[2]:
            creator["orcid"] = _strip_orcid(parts[2])
        creators.append(creator)
    return creators


def parse_keywords(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _cff_keywords(cff: dict[str, object]) -> list[str]:
    keywords = cff.get("keywords")
    if isinstance(keywords, list):
        return [str(item).strip() for item in keywords if str(item).strip()]
    return []


def _cff_license(cff: dict[str, object]) -> str:
    license_value = cff.get("license")
    if isinstance(license_value, list):
        return str(license_value[0]).strip() if license_value else ""
    return str(license_value or "").strip()


def build_metadata(
    *,
    cff: dict[str, object],
    title: str,
    creators_raw: str,
    description: str,
    upload_type: str,
    version: str,
    license_id: str,
    keywords_raw: str,
    extra: dict[str, object],
) -> dict[str, object]:
    """Merge CFF-derived fields with explicit inputs (explicit wins) and extra."""
    resolved_title = title.strip() or str(cff.get("title") or "").strip()
    if not resolved_title:
        raise CffError("no deposition title resolved from zenodo-title or CITATION.cff.")

    creators = parse_creators(creators_raw) if creators_raw.strip() else cff_creators(cff)
    if not creators:
        raise CffError("no deposition creators resolved from zenodo-creators or CITATION.cff.")

    resolved_description = description.strip() or str(cff.get("abstract") or "").strip()
    if not resolved_description:
        raise CffError(
            "no deposition description resolved from zenodo-description or CITATION.cff."
        )

    keywords = parse_keywords(keywords_raw)
    for keyword in _cff_keywords(cff):
        if keyword not in keywords:
            keywords.append(keyword)

    metadata: dict[str, object] = {
        "upload_type": upload_type,
        "title": resolved_title,
        "creators": creators,
        "description": resolved_description,
        "version": version,
    }
    resolved_license = license_id.strip() or _cff_license(cff)
    if resolved_license:
        metadata["license"] = resolved_license
    if keywords:
        metadata["keywords"] = keywords
    # The escape hatch fills advanced fields only; owned keys were already rejected.
    for key, value in extra.items():
        metadata[key] = value
    return metadata
