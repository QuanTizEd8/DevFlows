"""Unit tests for the zenodo-release workflow scripts and generated shape.

The credentialed side effects (GitHub Release creation, Zenodo token exchange, DOI
reservation/minting) cannot be reached from CI, so deposit.py runs against a fake
requests session, release.py against a fake gh, and the verify/parse/validate
matrices run directly. The hosted dry-run scenarios cover the credential-free
prepare chain end to end.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from devflows.catalog import load_workflow
from devflows.publish import (
    MAX_GENERATED_WORKFLOW_BYTES,
    build_published_workflow,
    caller_required_permissions,
    render_published_workflow,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO / "workflows" / "zenodo-release" / "scripts"

# Helper modules are imported by bare name (they are materialized next to the entry
# scripts at run time). The names are unique across the catalog (dist_manifest /
# hashing, not anaconda's manifest / digest), so this cannot collide in sys.modules.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import assets  # type: ignore  # noqa: E402
import cff  # type: ignore  # noqa: E402
import dist_manifest  # type: ignore  # noqa: E402
import hashing  # type: ignore  # noqa: E402
import metadata  # type: ignore  # noqa: E402
import zenodo_api  # type: ignore  # noqa: E402

_ENV_KEYS = (
    "PUBLISH_DRY_RUN_ENABLED",
    "PUBLISH_TIMEOUT_MINUTES",
    "RELEASE_ENABLED",
    "RELEASE_TAG",
    "RELEASE_NAME",
    "RELEASE_NOTES",
    "RELEASE_NOTES_FILE",
    "RELEASE_GENERATE_NOTES_ENABLED",
    "RELEASE_DRAFT_ENABLED",
    "RELEASE_PRERELEASE_ENABLED",
    "RELEASE_LATEST_ENABLED",
    "RELEASE_DISCUSSION_CATEGORY",
    "RELEASE_EXISTING_MODE",
    "RELEASE_ASSET_GLOBS",
    "RELEASE_ASSET_SOURCE_PATH",
    "RELEASE_ASSET_IF_NO_FILES_FOUND",
    "RELEASE_APPEND_DOI_ENABLED",
    "RELEASE_ENVIRONMENT_NAME",
    "RELEASE_TARGET",
    "RELEASE_TITLE",
    "RELEASE_BODY",
    "RELEASE_ASSET_LIST",
    "ZENODO_ENABLED",
    "ZENODO_SANDBOX_ENABLED",
    "ZENODO_PUBLISH_ENABLED",
    "ZENODO_PUBLISH_CONFIRM",
    "ZENODO_CONCEPT_DOI",
    "ZENODO_NEW_VERSION_FILE_MODE",
    "ZENODO_ENVIRONMENT_NAME",
    "ZENODO_UPLOAD_TYPE",
    "ZENODO_TITLE",
    "ZENODO_CREATORS",
    "ZENODO_DESCRIPTION",
    "ZENODO_VERSION",
    "ZENODO_LICENSE",
    "ZENODO_KEYWORDS",
    "ZENODO_METADATA_CFF_PATH",
    "ZENODO_METADATA_EXTRA",
    "ZENODO_ASSET_GLOBS",
    "ZENODO_ASSET_SOURCE_PATH",
    "ZENODO_ASSET_IF_NO_FILES_FOUND",
    "ZENODO_ASSET_LIST",
    "ZENODO_DOI",
    "ZENODO_STATE",
    "ZENODO_TOKEN",
    "ZENODO_TOKEN_PRESENT",
    "ZENODO_SANDBOX_TOKEN_PRESENT",
    "DEPOSITION_METADATA",
    "PUBLISH_DIST_MANIFEST",
    "ARTIFACT_DOWNLOAD_ENABLED",
    "ARTIFACT_DOWNLOAD_PATH",
    "GITHUB_WORKSPACE",
    "GITHUB_OUTPUT",
    "GITHUB_STEP_SUMMARY",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def _set(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return _set


# Enum inputs the generator always feeds a non-empty default; unit tests must seed
# them exactly as the workflow's env map does (the validation-failure harness reads
# these defaults from the workflow, but direct unit calls do not).
VALIDATE_DEFAULTS = {
    "RELEASE_EXISTING_MODE": "fail",
    "RELEASE_ASSET_IF_NO_FILES_FOUND": "error",
    "ZENODO_UPLOAD_TYPE": "software",
    "ZENODO_NEW_VERSION_FILE_MODE": "replace",
    "ZENODO_ASSET_IF_NO_FILES_FOUND": "error",
}


def _load(script: str) -> ModuleType:
    path = SCRIPT_DIR / script
    name = "zenodo_release_" + script.replace("-", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _parse_output(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if "<<" in line:
            name, _, delimiter = line.partition("<<")
            index += 1
            body: list[str] = []
            while index < len(lines) and lines[index] != delimiter:
                body.append(lines[index])
                index += 1
            parsed[name] = "\n".join(body)
        index += 1
    return parsed


def _sha_size(data: bytes) -> tuple[str, int]:
    return hashlib.sha256(data).hexdigest(), len(data)


# --------------------------------------------------------------------------- #
# dist_manifest.py                                                            #
# --------------------------------------------------------------------------- #
def _manifest(name: str = "pkg-0.1.0.tar.gz", data: bytes = b"x") -> dict:
    sha, size = _sha_size(data)
    return {"schema": 1, "files": [{"name": name, "sha256": sha, "size": size, "kind": "sdist"}]}


def test_parse_manifest_accepts_valid() -> None:
    parsed = dist_manifest.parse_manifest(json.dumps(_manifest()))
    entries = dist_manifest.manifest_entries(parsed)
    assert "pkg-0.1.0.tar.gz" in entries


@pytest.mark.parametrize(
    "raw, needle",
    [
        ("{not json", "not valid JSON"),
        ('{"schema": 2, "files": []}', "schema-1"),
        ('{"schema": 1, "files": []}', "non-empty list"),
        ('{"schema": 1, "files": [{"name": "", "sha256": "x", "size": 1}]}', "invalid name"),
        ('{"schema": 1, "files": [{"name": "a", "sha256": "z", "size": 1}]}', "invalid sha256"),
        (
            '{"schema": 1, "files": [{"name": "a", "sha256": "%s", "size": -1}]}' % ("a" * 64),
            "size",
        ),
    ],
)
def test_parse_manifest_rejects(raw: str, needle: str) -> None:
    with pytest.raises(dist_manifest.ManifestError, match=needle):
        dist_manifest.parse_manifest(raw)


def test_manifest_versions() -> None:
    manifest = {"schema": 1, "files": [{"name": "a", "version": "1.2.3"}, {"name": "b"}]}
    assert dist_manifest.manifest_versions(manifest) == {"1.2.3"}


# --------------------------------------------------------------------------- #
# hashing.py                                                                  #
# --------------------------------------------------------------------------- #
def test_hashing_verify_entries(tmp_path: Path) -> None:
    data = b"hello world\n"
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.tar.gz").write_bytes(data)
    sha, size = _sha_size(data)
    assert hashing.verify_entries(tmp_path, {"f.tar.gz": (sha, size)}) == ["f.tar.gz"]


def test_hashing_missing_and_mismatch(tmp_path: Path) -> None:
    with pytest.raises(hashing.DigestError, match="missing"):
        hashing.locate_by_name(tmp_path, "nope")
    data = b"data"
    (tmp_path / "f").write_bytes(data)
    sha, size = _sha_size(data)
    with pytest.raises(hashing.DigestError, match="size mismatch"):
        hashing.compare_entry(tmp_path / "f", "f", sha, size + 1)
    with pytest.raises(hashing.DigestError, match="sha256 mismatch"):
        hashing.compare_entry(tmp_path / "f", "f", "0" * 64, size)


def test_hashing_ambiguous(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "dup").write_bytes(b"1")
    (tmp_path / "b" / "dup").write_bytes(b"1")
    with pytest.raises(hashing.DigestError, match="more than one"):
        hashing.locate_by_name(tmp_path, "dup")


# --------------------------------------------------------------------------- #
# assets.py                                                                   #
# --------------------------------------------------------------------------- #
def test_resolve_globs_policies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    (tmp_path / "a.tar.gz").write_bytes(b"1")
    (tmp_path / "b.pdf").write_bytes(b"2")
    resolved = assets.resolve_globs(
        tmp_path, ["*.tar.gz", "*.pdf"], policy="error", field="zenodo-asset"
    )
    assert {p.name for p in resolved} == {"a.tar.gz", "b.pdf"}
    with pytest.raises(assets.AssetError, match="matched no files"):
        assets.resolve_globs(tmp_path, ["*.zip"], policy="error", field="zenodo-asset")
    assert assets.resolve_globs(tmp_path, ["*.zip"], policy="ignore", field="zenodo-asset") == []


def test_resolve_globs_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(assets.AssetError, match="without '..'"):
        assets.resolve_globs(tmp_path, ["../x"], policy="error", field="zenodo-asset")
    with pytest.raises(assets.AssetError, match="one of"):
        assets.resolve_globs(tmp_path, ["*"], policy="bogus", field="zenodo-asset")


def test_contained_dir_rejects_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    assert assets.contained_dir("sub/dir", field="p") == (tmp_path / "sub/dir").resolve()
    with pytest.raises(assets.AssetError, match="workspace-relative"):
        assets.contained_dir("../evil", field="p")
    with pytest.raises(assets.AssetError, match="workspace-relative"):
        assets.contained_dir("/abs", field="p")


# --------------------------------------------------------------------------- #
# metadata.py                                                                 #
# --------------------------------------------------------------------------- #
def test_validate_metadata_extra() -> None:
    assert metadata.validate_metadata_extra("") == {}
    assert metadata.validate_metadata_extra('{"communities": [{"identifier": "x"}]}') == {
        "communities": [{"identifier": "x"}]
    }
    with pytest.raises(metadata.MetadataError, match="must be a JSON object"):
        metadata.validate_metadata_extra("[1, 2]")
    with pytest.raises(metadata.MetadataError, match="not valid JSON"):
        metadata.validate_metadata_extra("{oops")
    for owned in ("doi", "prereserve_doi", "conceptdoi", "version", "creators"):
        with pytest.raises(metadata.MetadataError, match="owned"):
            metadata.validate_metadata_extra(json.dumps({owned: "x"}))


def test_require_metadata_complete() -> None:
    metadata.require_metadata_complete(title="T", creators="C", description="D")
    with pytest.raises(metadata.MetadataError, match="deposition metadata"):
        metadata.require_metadata_complete(title="", creators="C", description="D")


# --------------------------------------------------------------------------- #
# cff.py                                                                      #
# --------------------------------------------------------------------------- #
CFF_TEXT = """
cff-version: 1.2.0
title: My Tool
abstract: A great tool.
version: 2.0.0
license: MIT
keywords:
  - science
authors:
  - family-names: Doe
    given-names: Jane
    affiliation: Uni
    orcid: https://orcid.org/0000-0002-1825-0097
  - name: The Team
"""


def test_cff_creators_and_build(tmp_path: Path) -> None:
    cff_file = tmp_path / "CITATION.cff"
    cff_file.write_text(CFF_TEXT, encoding="utf-8")
    data = cff.load_cff(cff_file)
    creators = cff.cff_creators(data)
    assert creators[0] == {
        "name": "Doe, Jane",
        "affiliation": "Uni",
        "orcid": "0000-0002-1825-0097",
    }
    assert creators[1] == {"name": "The Team"}

    # CFF-derived when no explicit inputs.
    meta = cff.build_metadata(
        cff=data,
        title="",
        creators_raw="",
        description="",
        upload_type="software",
        version="0.1.0",
        license_id="",
        keywords_raw="",
        extra={},
    )
    assert meta["title"] == "My Tool"
    assert meta["description"] == "A great tool."
    assert meta["license"] == "MIT"
    assert meta["version"] == "0.1.0"
    assert "science" in meta["keywords"]


def test_cff_explicit_overrides(tmp_path: Path) -> None:
    cff_file = tmp_path / "CITATION.cff"
    cff_file.write_text(CFF_TEXT, encoding="utf-8")
    data = cff.load_cff(cff_file)
    meta = cff.build_metadata(
        cff=data,
        title="Override",
        creators_raw="Roe, Ann | Lab | 0000-0001-0000-0000",
        description="Explicit.",
        upload_type="dataset",
        version="9.9.9",
        license_id="Apache-2.0",
        keywords_raw="one\ntwo",
        extra={"access_right": "open"},
    )
    assert meta["title"] == "Override"
    assert meta["creators"] == [
        {"name": "Roe, Ann", "affiliation": "Lab", "orcid": "0000-0001-0000-0000"}
    ]
    assert meta["license"] == "Apache-2.0"
    assert meta["upload_type"] == "dataset"
    assert meta["access_right"] == "open"
    assert meta["keywords"][:2] == ["one", "two"]


def test_cff_build_requires_fields() -> None:
    with pytest.raises(cff.CffError, match="title"):
        cff.build_metadata(
            cff={},
            title="",
            creators_raw="",
            description="",
            upload_type="software",
            version="1",
            license_id="",
            keywords_raw="",
            extra={},
        )
    with pytest.raises(cff.CffError, match="creators"):
        cff.build_metadata(
            cff={"title": "T"},
            title="",
            creators_raw="",
            description="",
            upload_type="software",
            version="1",
            license_id="",
            keywords_raw="",
            extra={},
        )


# --------------------------------------------------------------------------- #
# zenodo_api.py                                                               #
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(self, status: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self._handlers: list[tuple[str, str, Any]] = []

    def on(self, method: str, substr: str, response: Any) -> FakeSession:
        self._handlers.append((method, substr, response))
        return self

    def _dispatch(self, method: str, url: str, **kw: Any) -> Any:
        self.calls.append((method, url, kw))
        for m, substr, resp in self._handlers:
            if m == method and substr in url:
                return resp
        raise AssertionError(f"unexpected {method} {url}")

    def get(self, url: str, **kw: Any) -> Any:
        return self._dispatch("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> Any:
        return self._dispatch("POST", url, **kw)

    def put(self, url: str, **kw: Any) -> Any:
        return self._dispatch("PUT", url, **kw)

    def delete(self, url: str, **kw: Any) -> Any:
        return self._dispatch("DELETE", url, **kw)


@pytest.mark.parametrize(
    "doi, expected",
    [("10.5281/zenodo.123456", "123456"), ("10.5072/zenodo.9", "9"), ("42", "42")],
)
def test_concept_recid(doi: str, expected: str) -> None:
    assert zenodo_api.concept_recid(doi) == expected


def test_concept_recid_rejects_garbage() -> None:
    with pytest.raises(zenodo_api.ZenodoApiError):
        zenodo_api.concept_recid("not-a-doi")


def test_client_raises_on_error_status() -> None:
    session = FakeSession().on("POST", "/deposit/depositions", FakeResponse(400, text="bad"))
    client = zenodo_api.ZenodoClient(session, base=zenodo_api.SANDBOX_BASE, token="t")
    with pytest.raises(zenodo_api.ZenodoApiError, match="HTTP 400"):
        client.create_deposition({})


def test_client_sends_bearer_token() -> None:
    session = FakeSession().on("POST", "/deposit/depositions", FakeResponse(201, {"id": 1}))
    client = zenodo_api.ZenodoClient(session, base=zenodo_api.PRODUCTION_BASE, token="secret")
    client.create_deposition({"title": "t"})
    _, url, kw = session.calls[0]
    assert url == "https://zenodo.org/api/deposit/depositions"
    assert kw["headers"]["Authorization"] == "Bearer secret"
    assert kw["json"] == {"metadata": {"title": "t"}}


# --------------------------------------------------------------------------- #
# deposit.py (run_deposit against a fake session)                             #
# --------------------------------------------------------------------------- #
def _draft_response(dep_id: int, doi: str) -> FakeResponse:
    return FakeResponse(
        201,
        {
            "id": dep_id,
            "links": {
                "bucket": f"https://b/{dep_id}",
                "html": f"https://zenodo.org/deposit/{dep_id}",
            },
            "metadata": {"prereserve_doi": {"doi": doi, "recid": dep_id}},
        },
    )


def test_run_deposit_new_draft(tmp_path: Path) -> None:
    deposit = _load("deposit.py")
    asset = tmp_path / "pkg.tar.gz"
    asset.write_bytes(b"data")
    session = (
        FakeSession()
        .on("POST", "/deposit/depositions", _draft_response(1, "10.5281/zenodo.1"))
        .on("PUT", "https://b/1", FakeResponse(201, {}))
    )
    client = zenodo_api.ZenodoClient(session, base=zenodo_api.PRODUCTION_BASE, token="t")
    outputs = deposit.run_deposit(
        client,
        {"title": "T"},
        [asset],
        concept_doi="",
        file_mode="replace",
        publish=False,
        sandbox=False,
    )
    assert outputs["zenodo-doi"] == "10.5281/zenodo.1"
    assert outputs["zenodo-state"] == "draft"
    assert outputs["zenodo-deposition-id"] == "1"
    # exactly one bucket upload happened.
    assert sum(1 for m, u, _ in session.calls if m == "PUT" and "https://b/1" in u) == 1


def test_run_deposit_publish(tmp_path: Path) -> None:
    deposit = _load("deposit.py")
    asset = tmp_path / "pkg.tar.gz"
    asset.write_bytes(b"data")
    published = FakeResponse(
        200,
        {
            "id": 1,
            "doi": "10.5281/zenodo.1",
            "conceptdoi": "10.5281/zenodo.0",
            "links": {"html": "https://zenodo.org/records/1"},
            "metadata": {},
        },
    )
    session = (
        FakeSession()
        .on("POST", "/deposit/depositions/1/actions/publish", FakeResponse(202, {}))
        .on("POST", "/deposit/depositions", _draft_response(1, "10.5281/zenodo.1"))
        .on("PUT", "https://b/1", FakeResponse(201, {}))
        .on("GET", "/deposit/depositions/1", published)
    )
    client = zenodo_api.ZenodoClient(session, base=zenodo_api.PRODUCTION_BASE, token="t")
    outputs = deposit.run_deposit(
        client,
        {"title": "T"},
        [asset],
        concept_doi="",
        file_mode="replace",
        publish=True,
        sandbox=False,
    )
    assert outputs["zenodo-state"] == "published"
    assert outputs["zenodo-concept-doi"] == "10.5281/zenodo.0"
    assert outputs["zenodo-record-url"] == "https://zenodo.org/records/1"


def test_run_deposit_newversion_replaces_files(tmp_path: Path) -> None:
    deposit = _load("deposit.py")
    asset = tmp_path / "pkg.tar.gz"
    asset.write_bytes(b"data")
    newversion = FakeResponse(
        201, {"links": {"latest_draft": "https://zenodo.org/api/deposit/depositions/2"}}
    )
    # get() and update_metadata() (PUT) require HTTP 200.
    draft = FakeResponse(
        200,
        {
            "id": 2,
            "links": {"bucket": "https://b/2", "html": "https://zenodo.org/deposit/2"},
            "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.2", "recid": 2}},
        },
    )
    session = (
        FakeSession()
        .on("POST", "/deposit/depositions/5/actions/newversion", newversion)
        .on("GET", "/deposit/depositions/2/files", FakeResponse(200, [{"id": "old"}]))
        .on("GET", "/deposit/depositions/2", draft)
        .on("PUT", "/deposit/depositions/2", draft)
        .on("DELETE", "/deposit/depositions/2/files/old", FakeResponse(204))
        .on("PUT", "https://b/2", FakeResponse(201, {}))
    )
    client = zenodo_api.ZenodoClient(session, base=zenodo_api.PRODUCTION_BASE, token="t")
    outputs = deposit.run_deposit(
        client,
        {"title": "T"},
        [asset],
        concept_doi="10.5281/zenodo.5",
        file_mode="replace",
        publish=False,
        sandbox=False,
    )
    assert outputs["zenodo-deposition-id"] == "2"
    assert any(m == "DELETE" for m, _, _ in session.calls), "inherited file should be deleted"


def test_deposit_main_dry_run_is_noop(env) -> None:
    deposit = _load("deposit.py")
    env(PUBLISH_DRY_RUN_ENABLED="true")
    assert deposit.main() == 0


# --------------------------------------------------------------------------- #
# release.py (perform_release against a fake gh)                              #
# --------------------------------------------------------------------------- #
class FakeGh:
    def __init__(self, exists: bool = False, url: str = "https://x/releases/tag/v1") -> None:
        self.exists = exists
        self.url = url
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        if args[:2] == ["release", "view"] and "-q" in args:
            return subprocess.CompletedProcess(args, 0, stdout=self.url + "\n", stderr="")
        if args[:2] == ["release", "view"]:
            return subprocess.CompletedProcess(args, 0 if self.exists else 1, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def test_release_create(env) -> None:
    release = _load("release.py")
    env(
        RELEASE_TAG="v1",
        RELEASE_TITLE="Title",
        RELEASE_EXISTING_MODE="fail",
        RELEASE_LATEST_ENABLED="true",
        RELEASE_ASSET_LIST="dist/a.tar.gz",
    )
    gh = FakeGh(exists=False)
    url = release.perform_release(gh, base_body="Body")
    assert url == gh.url
    create = next(c for c in gh.calls if c[:2] == ["release", "create"])
    assert "v1" in create and "--notes-file" in create and "dist/a.tar.gz" in create
    assert "--latest" in create


def test_release_fail_when_exists(env) -> None:
    release = _load("release.py")
    env(RELEASE_TAG="v1", RELEASE_EXISTING_MODE="fail")
    with pytest.raises(SystemExit, match="already exists"):
        release.perform_release(FakeGh(exists=True), base_body="")


def test_release_skip_when_exists(env) -> None:
    release = _load("release.py")
    env(RELEASE_TAG="v1", RELEASE_EXISTING_MODE="skip")
    gh = FakeGh(exists=True)
    url = release.perform_release(gh, base_body="")
    assert url == gh.url
    assert not any(c[:2] == ["release", "create"] for c in gh.calls)


def test_release_update_edits_and_uploads(env) -> None:
    release = _load("release.py")
    env(RELEASE_TAG="v1", RELEASE_EXISTING_MODE="update", RELEASE_ASSET_LIST="dist/a.tar.gz")
    gh = FakeGh(exists=True)
    release.perform_release(gh, base_body="")
    assert any(c[:2] == ["release", "edit"] for c in gh.calls)
    assert any(c[:2] == ["release", "upload"] for c in gh.calls)


def test_release_compose_body_doi_footer() -> None:
    release = _load("release.py")
    draft = release.compose_body(
        "Body", append_doi=True, doi="10.5281/zenodo.1", concept="10.5281/zenodo.0", state="draft"
    )
    assert "reserved" in draft and "10.5281/zenodo.1" in draft and "10.5281/zenodo.0" in draft
    published = release.compose_body(
        "", append_doi=True, doi="10.5281/zenodo.1", concept="", state="published"
    )
    assert "registered" in published
    assert (
        release.compose_body(
            "Body", append_doi=False, doi="10.5281/zenodo.1", concept="", state="draft"
        )
        == "Body"
    )
    assert (
        release.compose_body("Body", append_doi=True, doi="", concept="", state="draft") == "Body"
    )


def test_release_main_dry_run_is_noop(env) -> None:
    release = _load("release.py")
    env(PUBLISH_DRY_RUN_ENABLED="true")
    assert release.main() == 0


# --------------------------------------------------------------------------- #
# preflight-token.py                                                          #
# --------------------------------------------------------------------------- #
def test_preflight_token(env) -> None:
    preflight = _load("preflight-token.py")
    env(PUBLISH_DRY_RUN_ENABLED="true")
    assert preflight.main() == 0
    env(
        PUBLISH_DRY_RUN_ENABLED="false", ZENODO_SANDBOX_ENABLED="false", ZENODO_TOKEN_PRESENT="true"
    )
    assert preflight.main() == 0
    env(ZENODO_TOKEN_PRESENT="false")
    with pytest.raises(SystemExit, match="zenodo-token"):
        preflight.main()
    env(ZENODO_SANDBOX_ENABLED="true", ZENODO_SANDBOX_TOKEN_PRESENT="false")
    with pytest.raises(SystemExit, match="zenodo-sandbox-token"):
        preflight.main()
    env(ZENODO_SANDBOX_TOKEN_PRESENT="true")
    assert preflight.main() == 0


# --------------------------------------------------------------------------- #
# reverify.py                                                                 #
# --------------------------------------------------------------------------- #
def test_reverify_noop_without_manifest(env) -> None:
    reverify = _load("reverify.py")
    env()
    assert reverify.main() == 0


def test_reverify_verifies_and_fails(env, tmp_path: Path) -> None:
    reverify = _load("reverify.py")
    data = b"payload"
    (tmp_path / "pkg.tar.gz").write_bytes(data)
    manifest = _manifest("pkg.tar.gz", data)
    env(ZENODO_ASSET_SOURCE_PATH=str(tmp_path), PUBLISH_DIST_MANIFEST=json.dumps(manifest))
    assert reverify.main() == 0
    tampered = json.loads(json.dumps(manifest))
    tampered["files"][0]["sha256"] = "0" * 64
    env(PUBLISH_DIST_MANIFEST=json.dumps(tampered))
    with pytest.raises(SystemExit, match="re-verification failed"):
        reverify.main()


# --------------------------------------------------------------------------- #
# validate-inputs.py                                                          #
# --------------------------------------------------------------------------- #
def _run_validate(module: ModuleType) -> None:
    module.main()


def test_validate_accepts_release_only(env) -> None:
    env(RELEASE_ENABLED="true", RELEASE_TAG="v1.0.0", **VALIDATE_DEFAULTS)
    assert _load("validate-inputs.py").main() == 0


def test_validate_accepts_full_zenodo(env) -> None:
    env(
        RELEASE_ENABLED="true",
        RELEASE_TAG="v1.0.0",
        ZENODO_ENABLED="true",
        ZENODO_ENVIRONMENT_NAME="zenodo",
        ZENODO_TITLE="T",
        ZENODO_CREATORS="Doe, Jane",
        ZENODO_DESCRIPTION="D",
        ZENODO_ASSET_GLOBS="*.tar.gz",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        **VALIDATE_DEFAULTS,
    )
    assert _load("validate-inputs.py").main() == 0


@pytest.mark.parametrize(
    "overrides, needle",
    [
        ({"RELEASE_ENABLED": "false", "ZENODO_ENABLED": "false"}, "Nothing to do"),
        ({"RELEASE_ENABLED": "true", "RELEASE_TAG": "bad tag"}, "valid git ref"),
        ({"RELEASE_ENABLED": "true", "RELEASE_TAG": "v1..0"}, "valid git ref"),
        (
            {"RELEASE_ENABLED": "true", "RELEASE_NOTES": "a", "RELEASE_NOTES_FILE": "n.md"},
            "mutually exclusive",
        ),
        (
            {
                "RELEASE_ENABLED": "true",
                "RELEASE_DISCUSSION_CATEGORY": "General",
                "RELEASE_DRAFT_ENABLED": "true",
            },
            "release-draft-enabled",
        ),
        ({"RELEASE_ENABLED": "true", "RELEASE_EXISTING_MODE": "clobber"}, "must be one of"),
        (
            {
                "RELEASE_ENABLED": "true",
                "RELEASE_ASSET_GLOBS": "*.zip",
                "ARTIFACT_DOWNLOAD_ENABLED": "false",
            },
            "artifact-download channel",
        ),
        ({"RELEASE_ENABLED": "true", "RELEASE_NOTES_FILE": "../x"}, "workspace-relative"),
        (
            {"ZENODO_ENABLED": "true", "ZENODO_ENVIRONMENT_NAME": ""},
            "zenodo-environment-name is required",
        ),
        (
            {
                "ZENODO_ENABLED": "true",
                "ZENODO_ENVIRONMENT_NAME": "zenodo",
                "ZENODO_ASSET_GLOBS": "*.tar.gz",
                "ARTIFACT_DOWNLOAD_ENABLED": "true",
            },
            "deposition metadata",
        ),
        (
            {
                "ZENODO_ENABLED": "true",
                "ZENODO_ENVIRONMENT_NAME": "zenodo",
                "ZENODO_ASSET_GLOBS": "",
            },
            "zenodo-asset-globs is required",
        ),
        (
            {
                "ZENODO_ENABLED": "true",
                "ZENODO_ENVIRONMENT_NAME": "zenodo",
                "ZENODO_ASSET_GLOBS": "*.tar.gz",
                "ARTIFACT_DOWNLOAD_ENABLED": "true",
                "ZENODO_METADATA_EXTRA": '{"doi": "x"}',
            },
            "owned",
        ),
        (
            {
                "ZENODO_ENABLED": "true",
                "ZENODO_ENVIRONMENT_NAME": "zenodo",
                "ZENODO_ASSET_GLOBS": "*.tar.gz",
                "ARTIFACT_DOWNLOAD_ENABLED": "true",
                "ZENODO_TITLE": "T",
                "ZENODO_CREATORS": "Doe, Jane",
                "ZENODO_DESCRIPTION": "D",
                "PUBLISH_DIST_MANIFEST": "{not json",
            },
            "not valid JSON",
        ),
        (
            {
                "RELEASE_ENABLED": "false",
                "ZENODO_ENABLED": "true",
                "ZENODO_ENVIRONMENT_NAME": "zenodo",
                "ZENODO_ASSET_GLOBS": "*.tar.gz",
                "ARTIFACT_DOWNLOAD_ENABLED": "true",
                "ZENODO_TITLE": "T",
                "ZENODO_CREATORS": "Doe, Jane",
                "ZENODO_DESCRIPTION": "D",
                "ZENODO_PUBLISH_ENABLED": "true",
                "ZENODO_PUBLISH_CONFIRM": "wrong",
            },
            "zenodo-publish-confirm must equal release-tag",
        ),
    ],
)
def test_validate_rejects(env, overrides: dict[str, str], needle: str) -> None:
    base = {"RELEASE_TAG": "v1.0.0", **VALIDATE_DEFAULTS}
    base.update(overrides)
    env(**base)
    with pytest.raises(SystemExit, match=re.escape(needle)):
        _load("validate-inputs.py").main()


def test_validate_publish_confirm_accepts_matching_tag(env) -> None:
    env(
        RELEASE_ENABLED="false",
        ZENODO_ENABLED="true",
        RELEASE_TAG="v1.0.0",
        ZENODO_ENVIRONMENT_NAME="zenodo",
        ZENODO_ASSET_GLOBS="*.tar.gz",
        ARTIFACT_DOWNLOAD_ENABLED="true",
        ZENODO_TITLE="T",
        ZENODO_CREATORS="Doe, Jane",
        ZENODO_DESCRIPTION="D",
        ZENODO_PUBLISH_ENABLED="true",
        ZENODO_PUBLISH_CONFIRM="v1.0.0",
        **VALIDATE_DEFAULTS,
    )
    assert _load("validate-inputs.py").main() == 0


# --------------------------------------------------------------------------- #
# prepare.py end-to-end                                                       #
# --------------------------------------------------------------------------- #
def _prepare_env(env, tmp_path: Path, **overrides: str) -> Path:
    (tmp_path / "dl").mkdir(exist_ok=True)
    data = b"zenodo-release sdist fixture\n"
    (tmp_path / "dl" / "pkg-0.1.0.tar.gz").write_bytes(data)
    out = tmp_path / "out.txt"
    base = dict(
        GITHUB_WORKSPACE=str(tmp_path),
        RELEASE_ENABLED="true",
        RELEASE_TAG="v0.1.0",
        RELEASE_ASSET_GLOBS="*.tar.gz",
        ZENODO_ENABLED="true",
        ZENODO_TITLE="T",
        ZENODO_CREATORS="Doe, Jane",
        ZENODO_DESCRIPTION="D",
        ZENODO_ASSET_GLOBS="*.tar.gz",
        ARTIFACT_DOWNLOAD_PATH="dl",
        GITHUB_OUTPUT=str(out),
    )
    base.update(overrides)
    env(**base)
    return out


def test_prepare_emits_plan(env, tmp_path: Path) -> None:
    out = _prepare_env(env, tmp_path)
    assert _load("prepare.py").main() == 0
    parsed = _parse_output(out)
    assert parsed["package-version"] == "0.1.0"
    assert parsed["release-tag"] == "v0.1.0"
    assert parsed["release-asset-list"] == "dl/pkg-0.1.0.tar.gz"
    meta = json.loads(parsed["deposition-metadata"])
    assert meta["title"] == "T" and meta["version"] == "0.1.0"


def test_prepare_digest_verify_and_mismatch(env, tmp_path: Path) -> None:
    data = b"zenodo-release sdist fixture\n"
    sha, size = _sha_size(data)
    manifest = {"schema": 1, "files": [{"name": "pkg-0.1.0.tar.gz", "sha256": sha, "size": size}]}
    out = _prepare_env(env, tmp_path, PUBLISH_DIST_MANIFEST=json.dumps(manifest))
    assert _load("prepare.py").main() == 0
    assert _parse_output(out)["package-version"] == "0.1.0"

    bad = {"schema": 1, "files": [{"name": "pkg-0.1.0.tar.gz", "sha256": "0" * 64, "size": size}]}
    _prepare_env(env, tmp_path, PUBLISH_DIST_MANIFEST=json.dumps(bad))
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        _load("prepare.py").main()


def test_prepare_unlisted_asset_fails(env, tmp_path: Path) -> None:
    manifest = {"schema": 1, "files": [{"name": "other.tar.gz", "sha256": "a" * 64, "size": 1}]}
    _prepare_env(env, tmp_path, PUBLISH_DIST_MANIFEST=json.dumps(manifest))
    with pytest.raises(SystemExit, match="not covered by publish-dist-manifest"):
        _load("prepare.py").main()


def test_prepare_cff_metadata(env, tmp_path: Path) -> None:
    cff_file = tmp_path / "CITATION.cff"
    cff_file.write_text(CFF_TEXT, encoding="utf-8")
    out = _prepare_env(
        env,
        tmp_path,
        RELEASE_ENABLED="false",
        ZENODO_TITLE="",
        ZENODO_CREATORS="",
        ZENODO_DESCRIPTION="",
        ZENODO_METADATA_CFF_PATH="CITATION.cff",
    )
    assert _load("prepare.py").main() == 0
    meta = json.loads(_parse_output(out)["deposition-metadata"])
    assert meta["title"] == "My Tool"
    assert meta["version"] == "0.1.0"


# --------------------------------------------------------------------------- #
# Renovate pin registration                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("dep", ["pyyaml", "requests"])
def test_ephemeral_pin_matches_renovate_manager(dep: str) -> None:
    renovate = (REPO / "renovate.json5").read_text(encoding="utf-8")
    workflow = (REPO / "workflows" / "zenodo-release" / "workflow.yaml").read_text(encoding="utf-8")
    match_strings = re.findall(rf"'(--with \"{dep}==[^']*)'", renovate)
    assert len(match_strings) == 1, f"expected one {dep} matchString"
    configured = match_strings[0].replace("\\\\", "\\")
    python_pattern = re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", configured)
    match = re.search(python_pattern, workflow)
    assert match is not None, python_pattern
    assert re.fullmatch(r"[0-9]+(\.[0-9]+)*", match.group("currentValue"))


# --------------------------------------------------------------------------- #
# Generated workflow shape                                                    #
# --------------------------------------------------------------------------- #
def _published() -> dict:
    return build_published_workflow(load_workflow(REPO / "workflows" / "zenodo-release"))


def _steps(job: dict) -> list[dict]:
    return [step for step in job.get("steps", []) if isinstance(step, dict)]


def test_generated_workflow_stays_under_size_budget() -> None:
    rendered = render_published_workflow(load_workflow(REPO / "workflows" / "zenodo-release"))
    size = len(rendered.encode("utf-8"))
    assert size < 108_000, size
    assert MAX_GENERATED_WORKFLOW_BYTES == 115_000


def test_caller_required_permissions() -> None:
    assert caller_required_permissions(_published()) == {
        "actions": "read",
        "contents": "write",
        "discussions": "write",
    }


def test_zenodo_token_on_exactly_one_step() -> None:
    jobs = _published()["jobs"]
    deposit = jobs["zenodo-deposit"]
    token_steps = [s for s in _steps(deposit) if "ZENODO_TOKEN" in (s.get("env") or {})]
    assert len(token_steps) == 1
    # Never on the reverify, preflight, download, or materialize steps.
    for step in _steps(deposit):
        if step is token_steps[0]:
            continue
        assert "ZENODO_TOKEN" not in (step.get("env") or {})
    # The credential-free jobs never see the token.
    for job_id in ("validate", "prepare", "release"):
        for step in _steps(jobs[job_id]):
            assert "ZENODO_TOKEN" not in (step.get("env") or {})


def test_preflight_is_tokenless() -> None:
    deposit = _published()["jobs"]["zenodo-deposit"]
    preflight = next(
        s for s in _steps(deposit) if s.get("name") == "Assert Zenodo credential present"
    )
    env = preflight.get("env") or {}
    assert env["ZENODO_TOKEN_PRESENT"] == "${{ secrets.zenodo-token != '' }}"
    assert env["ZENODO_SANDBOX_TOKEN_PRESENT"] == "${{ secrets.zenodo-sandbox-token != '' }}"
    assert "ZENODO_TOKEN" not in env


def test_reverify_runs_before_token_step() -> None:
    steps = _steps(_published()["jobs"]["zenodo-deposit"])
    # Exclude the materialize step, whose heredoc inlines reverify.py's source.
    reverify = [
        i
        for i, s in enumerate(steps)
        if s.get("id") != "devflows-runtime" and "reverify.py" in str(s.get("run", ""))
    ]
    token = [i for i, s in enumerate(steps) if "ZENODO_TOKEN" in (s.get("env") or {})]
    assert len(reverify) == 1 and len(token) == 1
    assert reverify[0] < token[0]
    assert "ZENODO_TOKEN" not in (steps[reverify[0]].get("env") or {})


def test_deposit_binds_environment_and_serial_concurrency() -> None:
    deposit = _published()["jobs"]["zenodo-deposit"]
    assert deposit["environment"]["name"] == "${{ inputs.zenodo-environment-name }}"
    assert deposit["concurrency"]["group"] == "zenodo-release-${{ inputs.zenodo-environment-name }}"
    assert deposit["concurrency"]["cancel-in-progress"] is False
    assert "!inputs.publish-dry-run-enabled" in deposit["if"]
    assert "inputs.zenodo-enabled" in deposit["if"]


def test_validate_and_prepare_never_bind_environment() -> None:
    jobs = _published()["jobs"]
    for job_id in ("validate", "prepare"):
        assert "environment" not in jobs[job_id]
        assert "if" not in jobs[job_id]


def test_release_ordered_after_deposit_and_tolerates_skip() -> None:
    release = _published()["jobs"]["release"]
    assert "zenodo-deposit" in release["needs"]
    assert (
        "needs.zenodo-deposit.result == 'success' || needs.zenodo-deposit.result == 'skipped'"
        in release["if"]
    )
    assert "!inputs.publish-dry-run-enabled" in release["if"]


def test_no_checkout_in_credentialed_jobs() -> None:
    jobs = _published()["jobs"]
    for job_id in ("zenodo-deposit", "release"):
        for step in _steps(jobs[job_id]):
            assert "actions/checkout" not in str(step.get("uses", ""))


def test_interface_renames_and_shape() -> None:
    call = load_workflow(REPO / "workflows" / "zenodo-release").workflow_call
    inputs = set(call["inputs"])
    # harmonizer + lead renames applied
    assert "publish-dist-manifest" in inputs and "zenodo-files-manifest" not in inputs
    assert (
        "release-asset-if-no-files-found" in inputs and "release-asset-if-none-found" not in inputs
    )
    assert "zenodo-asset-if-no-files-found" in inputs and "zenodo-asset-if-none-found" not in inputs
    # independent target gating + publishing-tier machinery
    for name in (
        "release-enabled",
        "zenodo-enabled",
        "publish-dry-run-enabled",
        "zenodo-environment-name",
        "zenodo-publish-confirm",
        "zenodo-sandbox-enabled",
    ):
        assert name in inputs
    assert set(call["secrets"]) == {"zenodo-token", "zenodo-sandbox-token"}
    assert set(call["outputs"]) == {
        "package-version",
        "release-url",
        "release-tag",
        "zenodo-doi",
        "zenodo-concept-doi",
        "zenodo-record-url",
        "zenodo-deposition-id",
        "zenodo-state",
    }
