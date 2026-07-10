from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

MANIFEST_SCHEMA = 1
# Re-indexing the merged conda channel is done by the sibling
# reindex-conda-channel.py, a self-contained repodata.json generator with no
# conda dependency (see that file for why conda-index was dropped). Its only
# third-party need is zstandard, to decompress the ``.conda`` inner tarball; it is
# delivered through an ephemeral, pinned ``uv run --with`` environment so nothing
# is installed on the collect runner's interpreter. Pinned here, version-locked
# with the aggregation logic, rather than exposed as an input: re-indexing is an
# internal implementation detail.
ZSTANDARD_VERSION = "0.25.0"
REINDEX_SCRIPT = Path(__file__).with_name("reindex-conda-channel.py")


@dataclass(frozen=True)
class DistFile:
    """A single published distribution file and its computed metadata."""

    name: str
    path: Path
    sha256: str
    size: int
    kind: str  # "sdist" | "wheel" | "conda"
    version: str


def main() -> int:
    prefix = _required("DIST_ARTIFACT_PREFIX")
    dist_staging = _staging("DIST_STAGING")
    cibw_staging = _staging("CIBW_STAGING")
    conda_staging = _staging("CONDA_STAGING")
    wheels_out = Path(os.environ["WHEELS_OUT"]).resolve()
    sdist_out = Path(os.environ["SDIST_OUT"]).resolve()
    conda_out = Path(os.environ["CONDA_OUT"]).resolve()

    sdists = _assemble_flat(sources=[dist_staging], pattern="*.tar.gz", destination=sdist_out)
    wheels = _assemble_flat(
        sources=[dist_staging, cibw_staging], pattern="*.whl", destination=wheels_out
    )
    conda_packages = _assemble_conda_channel(conda_staging, conda_out)
    if conda_packages:
        _reindex_conda_channel(conda_out)

    files: list[DistFile] = []
    files += [_describe(path, "sdist") for path in sdists]
    files += [_describe(path, "wheel") for path in wheels]
    files += [_describe(path, "conda") for path in conda_packages]
    files.sort(key=lambda item: (item.kind, item.name))

    if not files:
        # validate rejects nothing-to-build calls and collect only runs when a
        # producer succeeded, so an empty aggregate means an upstream job produced
        # no files despite succeeding; fail rather than publish nothing.
        raise SystemExit("collect found no distribution files to aggregate.")

    version = _resolve_version(files)

    sdist_name = f"{prefix}-sdist" if sdists else ""
    wheels_name = f"{prefix}-wheels" if wheels else ""
    conda_name = f"{prefix}-conda-channel" if conda_packages else ""

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "files": [
            {"name": item.name, "sha256": item.sha256, "size": item.size, "kind": item.kind}
            for item in files
        ],
        "artifacts": {"sdist": sdist_name, "wheels": wheels_name, "conda-channel": conda_name},
    }
    sha256sums = "".join(f"{item.sha256}  {item.name}\n" for item in files)
    sha256sums_b64 = base64.b64encode(sha256sums.encode("utf-8")).decode("ascii")

    _write_outputs(
        {
            "sdist-artifact-name": sdist_name,
            "wheels-artifact-name": wheels_name,
            "conda-artifact-name": conda_name,
            "dist-sha256sums": sha256sums_b64,
            "dist-manifest": json.dumps(manifest, separators=(",", ":"), sort_keys=True),
            "package-version": version,
        }
    )
    _write_summary(manifest, version)
    return 0


def _assemble_flat(*, sources: list[Path], pattern: str, destination: Path) -> list[Path]:
    """Copy every file matching ``pattern`` from ``sources`` flat into ``destination``."""
    collected: list[Path] = []
    seen: set[str] = set()
    for source in sources:
        if not source.is_dir():
            continue
        for path in sorted(source.rglob(pattern)):
            if path.name in seen:
                raise SystemExit(
                    f"duplicate distribution file {path.name!r} across build jobs; "
                    "ensure matrix legs do not produce colliding wheels."
                )
            seen.add(path.name)
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / path.name
            shutil.copy2(path, target)
            collected.append(target)
    return collected


def _assemble_conda_channel(staging: Path, destination: Path) -> list[Path]:
    """Copy conda packages into ``destination/<subdir>/`` preserving their subdir.

    rattler-build writes each package to ``<output-dir>/<subdir>/<pkg>``; the
    immediate parent directory name is the conda subdir (noarch, linux-64, ...).
    """
    collected: list[Path] = []
    if not staging.is_dir():
        return collected
    seen: set[str] = set()
    for pattern in ("*.conda", "*.tar.bz2"):
        for path in sorted(staging.rglob(pattern)):
            subdir = path.parent.name
            key = f"{subdir}/{path.name}"
            if key in seen:
                continue
            seen.add(key)
            target_dir = destination / subdir
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / path.name
            shutil.copy2(path, target)
            collected.append(target)
    return collected


def _reindex_conda_channel(channel: Path) -> None:
    """Regenerate authoritative repodata.json across every subdir of the channel.

    Per-leg repodata only covers that leg's packages, so the merged channel needs
    a fresh index. The generation is done by reindex-conda-channel.py (no conda
    dependency), run through an ephemeral uv environment that supplies only a
    pinned zstandard for ``.conda`` decompression — nothing lands on the runner's
    interpreter.
    """
    subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            f"zstandard=={ZSTANDARD_VERSION}",
            "python",
            str(REINDEX_SCRIPT),
            str(channel),
        ],
        check=True,
    )


def _describe(path: Path, kind: str) -> DistFile:
    data = path.read_bytes()
    return DistFile(
        name=path.name,
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        kind=kind,
        version=_parse_version(path.name, kind),
    )


def _parse_version(filename: str, kind: str) -> str:
    if kind == "wheel":
        stem = filename[: -len(".whl")]
        parts = stem.split("-")
        if len(parts) < 5:
            raise SystemExit(f"cannot parse version from wheel filename {filename!r}.")
        return parts[1]
    if kind == "sdist":
        stem = filename[: -len(".tar.gz")]
        name, _, version = stem.rpartition("-")
        if not name or not version:
            raise SystemExit(f"cannot parse version from sdist filename {filename!r}.")
        return version
    # conda: <name>-<version>-<build>.<ext>; name may itself contain hyphens.
    ext = ".conda" if filename.endswith(".conda") else ".tar.bz2"
    stem = filename[: -len(ext)]
    segments = stem.rsplit("-", 2)
    if len(segments) != 3:
        raise SystemExit(f"cannot parse version from conda filename {filename!r}.")
    return segments[1]


def _resolve_version(files: list[DistFile]) -> str:
    versions = sorted({item.version for item in files})
    if len(versions) != 1:
        detail = ", ".join(f"{item.name}={item.version}" for item in files)
        raise SystemExit(
            f"produced distributions disagree on version ({detail}); refusing to "
            "publish a mixed-version build."
        )
    return versions[0]


def _staging(name: str) -> Path:
    value = os.environ.get(name, "")
    return Path(value).resolve() if value else Path("/nonexistent")


def _write_outputs(outputs: dict[str, str]) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        raise SystemExit("GITHUB_OUTPUT is not set.")
    with Path(github_output).open("a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            handle.write(_render_output(name, value))


def _render_output(name: str, value: str) -> str:
    """Render one GITHUB_OUTPUT entry using a collision-proof heredoc delimiter."""
    delimiter = f"ghadelim_{secrets.token_hex(16)}"
    if delimiter in value:  # pragma: no cover - astronomically unlikely
        raise SystemExit("output delimiter collision; retry.")
    return f"{name}<<{delimiter}\n{value}\n{delimiter}\n"


def _write_summary(manifest: dict[str, object], version: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## python-build distribution manifest",
        "",
        f"Package version: `{version}`",
        "",
        "| kind | file | sha256 | size |",
        "| --- | --- | --- | --- |",
    ]
    for entry in manifest["files"]:  # type: ignore[index]
        assert isinstance(entry, dict)
        lines.append(
            f"| {entry['kind']} | `{entry['name']}` | `{entry['sha256']}` | {entry['size']} |"
        )
    lines.append("")
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
