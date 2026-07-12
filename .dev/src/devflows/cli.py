from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from devflows.catalog import (
    CATALOG_DIR,
    PUBLISHED_DIR,
    load_catalog,
    validate_workflow,
)
from devflows.docs import write_generated_docs
from devflows.errors import DevflowsError
from devflows.project import find_root, load_project
from devflows.propagation import (
    changed_paths_since,
    propagation_violations,
    published_content_changed,
)
from devflows.publish import render_published_workflow, validate_publish_config
from devflows.scenarios import (
    run_local_scenarios,
    validate_scenarios,
    write_generated_test_workflows,
)
from devflows.schema import schema_errors

# The orphan sweep must skip BOTH the current internal namespace ("_", which owns
# every renamed internal workflow file) and the legacy "devflows-" prefix (kept for
# back-compat during the rename). Without "_" here, `devflows sync` would delete
# every generated `_scenarios-*.yaml`. Passed straight to str.startswith(tuple).
INTERNAL_PREFIX = ("_", "devflows-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="devflows")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Catalog root directory. Defaults to walking up to .config/project.yaml.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate", parents=[common], help="Validate workflow catalog metadata."
    )
    validate.add_argument("--include-drafts", action="store_true")

    sync = subparsers.add_parser(
        "sync", parents=[common], help="Sync catalog workflows into .github/workflows."
    )
    sync.add_argument("--check", action="store_true", help="Fail if published workflows are stale.")

    docs = subparsers.add_parser(
        "docs", parents=[common], help="Generate Sphinx workflow reference pages."
    )
    docs.add_argument(
        "--check",
        action="store_true",
        help="Render docs to a temporary directory and fail on render errors (does not write).",
    )

    test_generate = subparsers.add_parser(
        "test-generate", parents=[common], help="Generate workflow scenario test workflows."
    )
    test_generate.add_argument(
        "--check", action="store_true", help="Fail if generated test workflows are stale."
    )

    subparsers.add_parser(
        "test-local", parents=[common], help="Run local workflow scenario tests with act."
    )
    subparsers.add_parser(
        "release-check", parents=[common], help="Validate local release-please config."
    )
    propagation_check = subparsers.add_parser(
        "propagation-check",
        parents=[common],
        help="Fail when a shared-generator change alters a published workflow "
        "without a change release-please can attribute to it.",
    )
    propagation_check.add_argument(
        "--base",
        default=None,
        help="Base git ref to diff against. Defaults to the DEVFLOWS_BASE_SHA "
        "environment variable; the check is skipped when neither is set.",
    )
    subparsers.add_parser("list", parents=[common], help="List active workflow IDs.")

    args = parser.parse_args(argv)
    try:
        os.chdir(find_root(args.root))
        return _dispatch(args)
    except DevflowsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "validate":
        return _validate(include_drafts=args.include_drafts)
    if args.command == "sync":
        return _sync(check=args.check)
    if args.command == "docs":
        return _docs(check=args.check)
    if args.command == "test-generate":
        return _test_generate(check=args.check)
    if args.command == "test-local":
        return _test_local()
    if args.command == "release-check":
        return _release_check()
    if args.command == "propagation-check":
        return _propagation_check(base=args.base)
    if args.command == "list":
        workflows = load_catalog()
        for item in workflows:
            print(item.id)
        print(f"listed {len(workflows)} workflows", file=sys.stderr)
        return 0
    return 2


def _require_catalog(*, include_drafts: bool = False) -> list:
    if not CATALOG_DIR.is_dir():
        raise DevflowsError(f"catalog directory {CATALOG_DIR} does not exist.")
    workflows = load_catalog(include_drafts=include_drafts)
    if not workflows:
        raise DevflowsError(f"catalog directory {CATALOG_DIR} contains no workflows.")
    return workflows


def _validate(*, include_drafts: bool = False) -> int:
    # Loading the project verifies the identity config is present and well-formed.
    load_project()
    workflows = _require_catalog(include_drafts=include_drafts)
    errors: list[str] = []
    for item in workflows:
        errors.extend(schema_errors(item))
        errors.extend(validate_workflow(item))
        errors.extend(validate_publish_config(item))
    errors.extend(validate_scenarios(workflows))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"validated {len(workflows)} workflows", file=sys.stderr)
    return 0


def _sync(*, check: bool = False) -> int:
    workflows = _require_catalog()
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    changed: list[Path] = []
    for item in workflows:
        published = render_published_workflow(item).rstrip() + "\n"
        existing = (
            item.published_path.read_text(encoding="utf-8")
            if item.published_path.exists()
            else None
        )
        if existing != published:
            changed.append(item.published_path)
            if not check:
                item.published_path.write_text(published, encoding="utf-8")
    for orphan in _orphans(workflows):
        changed.append(orphan)
        if not check:
            if orphan.is_dir():
                shutil.rmtree(orphan)
            else:
                orphan.unlink()
    if changed:
        for path in sorted(set(changed)):
            print(path, file=sys.stderr)
        if check:
            print(
                "error: published workflows are stale (drift from workflows/<id>/ sources). "
                "This commonly follows a grouped action-pin bump that updated a source "
                "workflow.yaml but not its generated copy. Run `task sync` "
                "(or `pixi run -- devflows sync`) and commit the regenerated files above.",
                file=sys.stderr,
            )
        return 1 if check else 0
    print(f"synced {len(workflows)} workflows", file=sys.stderr)
    return 0


def _orphans(workflows: list) -> list[Path]:
    """Published entries with no owning workflow (stale YAML or leftover script dirs).

    Published workflows no longer carry a `.github/workflows/<id>/` script tree, so
    any non-internal directory there is orphaned, as is any `<name>.yaml`/`<name>.yml`
    that no active workflow produces. Internal files/dirs whose name starts with any
    INTERNAL_PREFIX entry (``_`` for the current internal namespace, ``devflows-`` for
    legacy back-compat) are left alone -- this is what keeps the generated
    ``_scenarios-*.yaml`` files from being swept.
    """
    expected = {item.published_path for item in workflows}
    orphans: list[Path] = []
    for entry in sorted(PUBLISHED_DIR.iterdir()):
        if entry.name.startswith(INTERNAL_PREFIX):
            continue
        if entry.is_dir():
            orphans.append(entry)
        elif entry.suffix in {".yaml", ".yml"} and entry not in expected:
            orphans.append(entry)
    return orphans


def _docs(*, check: bool = False) -> int:
    load_project()
    workflows = _require_catalog()
    if check:
        # docs/reference/ is a gitignored build artifact, so there is no committed
        # baseline to diff against. Render to a throwaway directory instead and let
        # any render error (missing fixture, template failure) surface as nonzero.
        with tempfile.TemporaryDirectory(prefix="devflows-docs-check-") as temporary_dir:
            write_generated_docs(workflows, output_dir=Path(temporary_dir) / "reference")
        print(f"rendered docs for {len(workflows)} workflows", file=sys.stderr)
        return 0

    changed = write_generated_docs(workflows)
    for path in changed:
        print(path, file=sys.stderr)
    return 0


def _test_generate(*, check: bool = False) -> int:
    workflows = _require_catalog()
    changed = write_generated_test_workflows(workflows, check=check)
    if changed:
        for path in changed:
            print(path, file=sys.stderr)
        return 1 if check else 0
    return 0


def _test_local() -> int:
    return run_local_scenarios(_require_catalog())


def _release_check() -> int:
    config_path = Path(".github/release-please/config.json")
    manifest_path = Path(".github/release-please/manifest.json")
    if not config_path.is_file() or not manifest_path.is_file():
        raise DevflowsError("release-please config or manifest is missing.")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    workflows = _require_catalog()
    expected_packages = {f"workflows/{item.id}" for item in workflows}
    configured_packages = set(config.get("packages", {}))
    errors: list[str] = []

    if config.get("tag-separator") != "/":
        errors.append(f"{config_path}: tag-separator must be '/'.")
    if configured_packages != expected_packages:
        errors.append(
            f"{config_path}: packages must match active workflows: {sorted(expected_packages)}."
        )
    if set(manifest) != expected_packages:
        errors.append(
            f"{manifest_path}: manifest entries must match active workflows: "
            f"{sorted(expected_packages)}."
        )
    for item in workflows:
        package_path = f"workflows/{item.id}"
        package_config = config.get("packages", {}).get(package_path, {})
        if package_config.get("component") != item.id:
            errors.append(f"{config_path}: {package_path} component must be {item.id!r}.")
        if package_config.get("package-name") != item.id:
            errors.append(f"{config_path}: {package_path} package-name must be {item.id!r}.")
        release = item.metadata.get("release", {}) or {}
        if package_config.get("release-type") != release.get("type"):
            errors.append(
                f"{config_path}: {package_path} release-type must match devflow release.type."
            )
        errors.extend(_release_major_errors(item, manifest, package_path, manifest_path))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Release configuration is valid.")
    return 0


def _propagation_check(*, base: str | None) -> int:
    base_ref = base or os.environ.get("DEVFLOWS_BASE_SHA") or ""
    if not base_ref:
        print(
            "propagation-check: no base ref (pass --base or set DEVFLOWS_BASE_SHA); skipping.",
            file=sys.stderr,
        )
        return 0
    workflows = _require_catalog()
    changed = changed_paths_since(base_ref)
    violations = propagation_violations(
        changed,
        [item.id for item in workflows],
        # Drop candidates whose published output only changed cosmetically (same
        # parsed content); a formatting-only re-render strands no consumer.
        published_semantically_changed=lambda wid: published_content_changed(base_ref, wid),
    )
    if violations:
        for violation in violations:
            print(f"error: {violation}", file=sys.stderr)
        return 1
    print(f"propagation-check: {len(workflows)} workflows propagate cleanly.", file=sys.stderr)
    return 0


def _release_major_errors(item, manifest, package_path: str, manifest_path: Path) -> list[str]:
    release = item.metadata.get("release", {}) or {}
    declared_major = release.get("major")
    if declared_major is None:
        return [f"{item.metadata_path}: release.major is required."]
    manifest_version = manifest.get(package_path)
    if not isinstance(manifest_version, str) or "." not in manifest_version:
        return [f"{manifest_path}: {package_path} must declare a semver version."]
    manifest_major = manifest_version.split(".", 1)[0]
    if manifest_major != str(declared_major):
        return [
            f"{manifest_path}: {package_path} version {manifest_version!r} major "
            f"({manifest_major}) must match devflow release.major ({declared_major})."
        ]
    return []
