from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

# Only these kinds are ever uploaded to PyPI/TestPyPI. The manifest may also list
# conda-kind files (python-build emits one manifest for every flavor); those are
# ignored here, and any conda file that actually reaches the publish directory is
# rejected as an unlisted stray below.
PUBLISHABLE_KINDS = {"sdist", "wheel"}
_INDEX_PROJECT_BASE = {
    "pypi": "https://pypi.org",
    "testpypi": "https://test.pypi.org",
}
_SDIST_SUFFIX = ".tar.gz"
_WHEEL_SUFFIX = ".whl"


@dataclass(frozen=True)
class Expected:
    """A manifest entry for an sdist/wheel that must be present and byte-matched."""

    name: str
    sha256: str
    size: int
    kind: str


def main() -> int:
    """Verify the staged distributions against python-build's dist-manifest.

    Recomputes sha256 AND size for every file and matches them bidirectionally
    against the manifest's sdist/wheel subset: every staged file must be a listed
    distribution with a matching digest and size, and every listed sdist/wheel must
    be present. Parses a single consistent (package-name, version) pair, enforces
    publish-expected-version when set, then stages only the verified files into a
    workspace-relative directory the publish job hands to gh-action-pypi-publish.

    Runs in the credential-free verify job and again, atomically, inside the
    credentialed publish job immediately before upload (python-build uploads with
    overwrite: true, so a cross-job artifact handoff is a TOCTOU window).
    """
    manifest = _parse_manifest(os.environ.get("PUBLISH_DIST_MANIFEST", ""))
    listed = _manifest_files(manifest)
    expected = {entry.name: entry for entry in listed if entry.kind in PUBLISHABLE_KINDS}
    if not expected:
        raise SystemExit(
            "dist-manifest lists no sdist or wheel distributions to publish; "
            "pypi-publish uploads only sdist and wheel kinds."
        )

    dist_path = os.environ.get("PUBLISH_DIST_PATH", "").strip()
    root = _resolve_directory(dist_path)
    staged = _scan_files(root)

    _match_bidirectional(expected, staged, listed, dist_path)
    for name, entry in sorted(expected.items()):
        _verify_digest(name, staged[name], entry)

    package_name, version = _resolve_identity(
        expected, os.environ.get("PUBLISH_EXPECTED_VERSION", "").strip()
    )
    normalized = _normalize_name(package_name)
    release_url = _release_url(os.environ.get("PUBLISH_INDEX", "").strip(), normalized, version)

    _stage_verified(expected, staged)

    _emit_outputs(
        {
            "package-name": normalized,
            "package-version": version,
            "release-url": release_url,
        }
    )
    _write_summary(expected, staged, normalized, version)
    return 0


def _parse_manifest(raw: str) -> dict[str, object]:
    raw = raw.strip()
    if not raw:
        raise SystemExit("publish-dist-manifest is empty; cannot verify distributions.")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"publish-dist-manifest is not valid JSON: {error}.") from None
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise SystemExit("publish-dist-manifest must be a schema-1 JSON object.")
    return manifest


def _manifest_files(manifest: dict[str, object]) -> list[Expected]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SystemExit("publish-dist-manifest 'files' must be a list.")
    entries: list[Expected] = []
    for raw_entry in files:
        if not isinstance(raw_entry, dict):
            raise SystemExit("each dist-manifest file entry must be an object.")
        name = raw_entry.get("name")
        sha256 = raw_entry.get("sha256")
        size = raw_entry.get("size")
        kind = raw_entry.get("kind")
        if not isinstance(name, str) or not name:
            raise SystemExit(f"dist-manifest file entry has an invalid name: {raw_entry!r}.")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise SystemExit(f"dist-manifest entry {name!r} has an invalid sha256.")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise SystemExit(f"dist-manifest entry {name!r} has an invalid size.")
        if not isinstance(kind, str):
            raise SystemExit(f"dist-manifest entry {name!r} has an invalid kind.")
        entries.append(Expected(name=name, sha256=sha256, size=size, kind=kind))
    return entries


def _resolve_directory(dist_path: str) -> Path:
    if not dist_path:
        raise SystemExit("publish-dist-path is empty; cannot locate the distributions.")
    workspace = Path(os.environ.get("GITHUB_WORKSPACE") or Path.cwd()).resolve()
    root = (workspace / dist_path).resolve()
    if root != workspace and workspace not in root.parents:
        raise SystemExit(f"publish-dist-path must stay inside the workspace: {dist_path}.")
    if not root.is_dir():
        raise SystemExit(f"publish-dist-path does not exist or is not a directory: {dist_path}.")
    return root


def _scan_files(root: Path) -> dict[str, Path]:
    """Every regular file under ``root``, keyed by basename (must be unique)."""
    staged: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in staged:
            raise SystemExit(
                f"duplicate distribution filename {path.name!r} under the publish "
                "directory; refusing to publish an ambiguous set."
            )
        staged[path.name] = path
    return staged


def _match_bidirectional(
    expected: dict[str, Expected],
    staged: dict[str, Path],
    listed: list[Expected],
    dist_path: str,
) -> None:
    listed_by_name = {entry.name: entry for entry in listed}
    for name in sorted(set(staged) - set(expected)):
        entry = listed_by_name.get(name)
        if entry is not None and entry.kind not in PUBLISHABLE_KINDS:
            raise SystemExit(
                f"{name} is a {entry.kind}-kind file in {dist_path}; pypi-publish uploads "
                "only sdist and wheel distributions. Narrow the artifact-download pattern."
            )
        raise SystemExit(
            f"{name} is present in {dist_path} but is not a distribution listed in the "
            "manifest; refusing to publish an unverified file."
        )
    for name in sorted(set(expected) - set(staged)):
        raise SystemExit(
            f"{name} is listed in the manifest but missing from {dist_path}; refusing to "
            "publish a partial distribution set."
        )


def _verify_digest(name: str, path: Path, entry: Expected) -> None:
    data = path.read_bytes()
    actual_size = len(data)
    if actual_size != entry.size:
        raise SystemExit(
            f"size mismatch for {name}: manifest {entry.size} bytes, on disk {actual_size}."
        )
    actual_sha = hashlib.sha256(data).hexdigest()
    if actual_sha != entry.sha256:
        raise SystemExit(
            f"sha256 mismatch for {name}: manifest {entry.sha256}, on disk {actual_sha}."
        )


def _resolve_identity(expected: dict[str, Expected], expected_version: str) -> tuple[str, str]:
    names: set[str] = set()
    versions: set[str] = set()
    for entry in expected.values():
        name, version = _parse_dist_filename(entry.name, entry.kind)
        names.add(_normalize_name(name))
        versions.add(version)
    if len(versions) != 1:
        raise SystemExit(
            f"distributions disagree on version ({sorted(versions)}); refusing to publish "
            "a mixed-version set."
        )
    if len(names) != 1:
        raise SystemExit(
            f"distributions disagree on package name ({sorted(names)}); refusing to publish."
        )
    version = versions.pop()
    if expected_version and version != expected_version:
        raise SystemExit(
            f"publish-expected-version {expected_version!r} does not match the distribution "
            f"version {version!r}; refusing to publish a version-skewed set."
        )
    return names.pop(), version


def _parse_dist_filename(filename: str, kind: str) -> tuple[str, str]:
    if kind == "wheel":
        if not filename.endswith(_WHEEL_SUFFIX):
            raise SystemExit(f"wheel {filename!r} does not end with {_WHEEL_SUFFIX}.")
        parts = filename[: -len(_WHEEL_SUFFIX)].split("-")
        if len(parts) < 5:
            raise SystemExit(f"cannot parse name/version from wheel filename {filename!r}.")
        return parts[0], parts[1]
    if not filename.endswith(_SDIST_SUFFIX):
        raise SystemExit(
            f"sdist {filename!r} does not end with {_SDIST_SUFFIX} (PEP 625 gzip sdist)."
        )
    stem = filename[: -len(_SDIST_SUFFIX)]
    name, _, version = stem.rpartition("-")
    if not name or not version:
        raise SystemExit(f"cannot parse name/version from sdist filename {filename!r}.")
    return name, version


def _normalize_name(name: str) -> str:
    """PEP 503 normalized project name (as PyPI uses it in project URLs)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _release_url(index: str, normalized_name: str, version: str) -> str:
    base = _INDEX_PROJECT_BASE.get(index)
    if base is None:
        raise SystemExit(f"unknown publish-index {index!r}; expected 'pypi' or 'testpypi'.")
    return f"{base}/project/{normalized_name}/{version}/"


def _stage_verified(expected: dict[str, Expected], staged: dict[str, Path]) -> None:
    """Copy only the digest-verified files into a fresh workspace-relative dir.

    gh-action-pypi-publish runs an inner Docker container whose entrypoint globs
    packages-dir/* inside the /github/workspace mount, so the staging directory
    MUST live under the workspace (an out-of-workspace $RUNNER_TEMP path is invisible
    to the container). Staging isolates the exact verified subset from any stray file
    in the download directory, so the upload never carries an unverified distribution.
    """
    stage_dir = os.environ.get("DEVFLOWS_STAGE_DIR", "").strip()
    if not stage_dir:
        raise SystemExit("DEVFLOWS_STAGE_DIR is not set; cannot stage verified distributions.")
    workspace = Path(os.environ.get("GITHUB_WORKSPACE") or Path.cwd()).resolve()
    target = (workspace / stage_dir).resolve()
    if target != workspace and workspace not in target.parents:
        raise SystemExit(f"DEVFLOWS_STAGE_DIR must stay inside the workspace: {stage_dir}.")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in expected:
        shutil.copy2(staged[name], target / name)


def _emit_outputs(outputs: dict[str, str]) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            handle.write(_render_output(name, value))


def _render_output(name: str, value: str) -> str:
    """Render one GITHUB_OUTPUT entry with a collision-proof heredoc delimiter."""
    delimiter = f"ghadelim_{secrets.token_hex(16)}"
    if delimiter in value:  # pragma: no cover - astronomically unlikely
        raise SystemExit("output delimiter collision; retry.")
    return f"{name}<<{delimiter}\n{value}\n{delimiter}\n"


def _write_summary(
    expected: dict[str, Expected],
    staged: dict[str, Path],
    normalized_name: str,
    version: str,
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## pypi-publish verified distributions",
        "",
        f"Package: `{normalized_name}` version `{version}`",
        "",
        "| kind | file | sha256 | size |",
        "| --- | --- | --- | --- |",
    ]
    for name, entry in sorted(expected.items()):
        lines.append(f"| {entry.kind} | `{name}` | `{entry.sha256}` | {entry.size} |")
    lines.append("")
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
