"""Credential-free supply-chain guard and dry-run plan computation (verify job).

Recomputes the sha256 AND size of every ``.conda`` file and matches them
bidirectionally against the caller-supplied dist manifest, then derives the
staged / promote / remove plans and emits them as step outputs plus a job-summary
of the planned versions and specs -- the whole publish plan, without a token. The
exact anaconda-client argv is (re-)built by each credentialed job. Imports the
sibling modules parsing / digest / manifest.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import digest
import parsing


def main() -> int:
    try:
        return _run()
    except parsing.SpecError as error:
        raise SystemExit(str(error)) from error


def _run() -> int:
    owner = os.environ["PUBLISH_OWNER"].strip()
    upload_enabled = _bool("UPLOAD_ENABLED")
    promote_enabled = _bool("PROMOTE_ENABLED")
    maintain_enabled = _bool("MAINTAIN_ENABLED")

    version = ""
    staged_specs: list[str] = []
    uploaded_files: list[str] = []
    if upload_enabled:
        verified = _verify()
        version = digest.resolve_version(
            verified, expected=os.environ.get("PUBLISH_EXPECTED_VERSION", "")
        )
        uploaded_files = [item.name for item in verified]
        staged_specs = sorted(
            {parsing.owner_qualified(owner, f"{item.package}/{item.version}") for item in verified}
        )

    promoted_specs = _promote_targets(owner, staged_specs) if promote_enabled else []

    removed_specs: list[str] = []
    if maintain_enabled:
        removed_specs = [
            parsing.owner_qualified(owner, spec)
            for spec in parsing.validate_spec_list(
                os.environ.get("MAINTAIN_REMOVE_SPECS", ""), field="maintain-remove-specs"
            )
        ]

    _write_outputs(
        {
            "package-version": version,
            "staged-specs": "\n".join(staged_specs),
            "uploaded-files": "\n".join(uploaded_files),
            "promoted-specs": "\n".join(promoted_specs),
            "removed-specs": "\n".join(removed_specs),
        }
    )
    _write_summary(
        version=version,
        staged_specs=staged_specs,
        promoted_specs=promoted_specs,
        removed_specs=removed_specs,
    )
    return 0


def _verify() -> list[digest.CondaFile]:
    dist_path = Path(os.environ["PUBLISH_DIST_PATH"]).resolve()
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    if workspace != dist_path and workspace not in dist_path.parents:
        raise SystemExit(f"publish-dist-path {dist_path} must stay inside the workspace.")
    manifest_raw = os.environ.get("PUBLISH_DIST_MANIFEST", "").strip()
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"publish-dist-manifest is not valid JSON: {error}.") from error
    if not isinstance(manifest, dict):
        raise SystemExit("publish-dist-manifest must be a JSON object.")
    try:
        return digest.verify_files_against_manifest(dist_path, manifest)
    except parsing.SpecError as error:
        raise SystemExit(str(error)) from error


def _promote_targets(owner: str, staged_specs: list[str]) -> list[str]:
    raw = os.environ.get("PROMOTE_SPECS", "")
    if parsing.parse_spec_list(raw):
        try:
            validated = parsing.validate_spec_list(raw, field="promote-specs")
        except parsing.SpecError as error:
            raise SystemExit(str(error)) from error
        return [parsing.owner_qualified(owner, spec) for spec in validated]
    # Chained mode: promote exactly the staging specs derived from the verified set.
    return list(staged_specs)


def _write_outputs(outputs: dict[str, str]) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        raise SystemExit("GITHUB_OUTPUT is not set.")
    with Path(github_output).open("a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            handle.write(_render_output(name, value))


def _render_output(name: str, value: str) -> str:
    delimiter = f"ghadelim_{secrets.token_hex(16)}"
    if delimiter in value:  # pragma: no cover - astronomically unlikely
        raise SystemExit("output delimiter collision; retry.")
    return f"{name}<<{delimiter}\n{value}\n{delimiter}\n"


def _write_summary(
    *,
    version: str,
    staged_specs: list[str],
    promoted_specs: list[str],
    removed_specs: list[str],
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = ["## anaconda-publish plan", ""]
    if version:
        lines += [f"Package version: `{version}`", ""]
    for title, specs in (
        ("Upload (stage)", staged_specs),
        ("Promote", promoted_specs),
        ("Remove", removed_specs),
    ):
        if not specs:
            continue
        lines += [f"### {title}", ""]
        lines += [f"- `{spec}`" for spec in specs]
        lines += [""]
    if len(lines) == 2:
        lines += ["No operations planned.", ""]
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
