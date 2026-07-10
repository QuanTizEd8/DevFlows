"""Credential-free supply-chain guard and dry-run plan computation.

Runs in the ``verify`` job (and again, with EMIT_PLAN=false, as the tokenless
re-verification step inside the ``upload`` job). When upload-enabled it downloads
nothing itself (the generated artifact-download channel does) but recomputes the
sha256 AND size of every ``.conda`` file and matches them bidirectionally against
the caller-supplied dist manifest. It then derives the staged/promote/remove
plans and emits them as outputs plus a job summary of the exact argv each
credentialed job would run — the whole publish plan, produced without a token, so
a dry-run proves the wiring while every environment-bound job stays skipped.

Imports the sibling ``specs.py`` (a ``${DEVFLOWS_SCRIPT_ROOT}/anaconda-publish/
specs.py`` comment in the step run body makes the sync step inline it).
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import specs


def main() -> int:
    try:
        return _run()
    except specs.SpecError as error:
        raise SystemExit(str(error)) from error


def _run() -> int:
    owner = os.environ["PUBLISH_OWNER"].strip()
    server_url = os.environ.get("PUBLISH_SERVER_URL", "")
    # The plan's argv reflect the version each credentialed job resolves the same
    # way (override or the specs.py pin), so the dry-run summary is faithful.
    client_version = specs.resolve_client_version(os.environ.get("PUBLISH_CLIENT_VERSION", ""))
    emit_plan = _bool("EMIT_PLAN", default=True)

    upload_enabled = _bool("UPLOAD_ENABLED")
    promote_enabled = _bool("PROMOTE_ENABLED")
    maintain_enabled = _bool("MAINTAIN_ENABLED")

    version = ""
    verified: list[specs.CondaFile] = []
    if upload_enabled:
        verified = _verify(owner, server_url)
        version = specs.resolve_version(
            verified, expected=os.environ.get("PUBLISH_EXPECTED_VERSION", "")
        )

    if not emit_plan:
        # Re-verification pass inside the credentialed job: digests and version are
        # checked above; there is nothing to emit or plan.
        return 0

    staged_specs: list[str] = []
    uploaded_files: list[str] = []
    upload_plan: list[list[str]] = []
    if upload_enabled:
        uploaded_files = [item.name for item in verified]
        staged_specs = sorted(
            {specs.owner_qualified(owner, f"{item.package}/{item.version}") for item in verified}
        )
        mode = specs.validate_existing_mode(os.environ.get("UPLOAD_EXISTING_MODE", "fail"))
        extra = specs.parse_extra_arguments(
            os.environ.get("UPLOAD_ARGUMENTS", ""), field="upload-arguments"
        )
        upload_label = specs.validate_label(os.environ["UPLOAD_LABEL"], field="upload-label")
        upload_plan = [
            specs.uvx_wrap(
                client_version,
                specs.build_upload_argv(
                    server_url=server_url,
                    owner=owner,
                    label=upload_label,
                    mode=mode,
                    extra_arguments=extra,
                    file_path=str(item.path),
                ),
            )
            for item in verified
        ]

    promoted_specs: list[str] = []
    promote_plan: list[list[str]] = []
    if promote_enabled:
        promoted_specs = _promote_targets(owner, staged_specs)
        upload_label = specs.validate_label(os.environ["UPLOAD_LABEL"], field="upload-label")
        promote_label = specs.validate_label(os.environ["PROMOTE_LABEL"], field="promote-label")
        promote_plan = [
            specs.uvx_wrap(
                client_version,
                specs.build_move_argv(
                    server_url=server_url,
                    from_label=upload_label,
                    to_label=promote_label,
                    target=target,
                ),
            )
            for target in promoted_specs
        ]

    removed_specs: list[str] = []
    remove_plan: list[list[str]] = []
    if maintain_enabled:
        removed_specs = [
            specs.owner_qualified(owner, spec)
            for spec in specs.validate_spec_list(
                os.environ.get("MAINTAIN_REMOVE_SPECS", ""), field="maintain-remove-specs"
            )
        ]
        remove_plan = [
            specs.uvx_wrap(
                client_version, specs.build_remove_argv(server_url=server_url, target=target)
            )
            for target in removed_specs
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
        upload_plan=upload_plan,
        promote_plan=promote_plan,
        remove_plan=remove_plan,
    )
    return 0


def _verify(owner: str, server_url: str) -> list[specs.CondaFile]:
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
        return specs.verify_files_against_manifest(dist_path, manifest)
    except specs.SpecError as error:
        raise SystemExit(str(error)) from error


def _promote_targets(owner: str, staged_specs: list[str]) -> list[str]:
    explicit = specs.parse_spec_list(os.environ.get("PROMOTE_SPECS", ""))
    if explicit:
        try:
            validated = specs.validate_spec_list(
                os.environ.get("PROMOTE_SPECS", ""), field="promote-specs"
            )
        except specs.SpecError as error:
            raise SystemExit(str(error)) from error
        return [specs.owner_qualified(owner, spec) for spec in validated]
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
    upload_plan: list[list[str]],
    promote_plan: list[list[str]],
    remove_plan: list[list[str]],
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = ["## anaconda-publish plan", ""]
    if version:
        lines += [f"Package version: `{version}`", ""]
    for title, plan in (
        ("Upload", upload_plan),
        ("Promote", promote_plan),
        ("Remove", remove_plan),
    ):
        if not plan:
            continue
        lines += [f"### {title}", "", "```"]
        lines += [" ".join(argv) for argv in plan]
        lines += ["```", ""]
    if len(lines) == 2:
        lines += ["No operations planned.", ""]
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
