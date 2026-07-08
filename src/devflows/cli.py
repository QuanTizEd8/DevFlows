from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
import tempfile
from pathlib import Path

from devflows.catalog import PUBLISHED_DIR, load_catalog, validate_workflow
from devflows.docs import write_generated_docs
from devflows.scenarios import (
    run_local_scenarios,
    validate_scenarios,
    write_generated_test_workflows,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="devflows")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate workflow catalog metadata.")
    validate.add_argument("--include-drafts", action="store_true")

    sync = subparsers.add_parser("sync", help="Sync catalog workflows into .github/workflows.")
    sync.add_argument("--check", action="store_true", help="Fail if published workflows are stale.")

    docs = subparsers.add_parser("docs", help="Generate Sphinx workflow reference pages.")
    docs.add_argument("--check", action="store_true", help="Fail if generated docs are stale.")

    test_generate = subparsers.add_parser(
        "test-generate", help="Generate workflow scenario test workflows."
    )
    test_generate.add_argument(
        "--check", action="store_true", help="Fail if generated test workflows are stale."
    )

    subparsers.add_parser("test-local", help="Run local workflow scenario tests with act.")

    subparsers.add_parser("release-check", help="Validate local release-please config.")

    subparsers.add_parser("list", help="List active workflow IDs.")

    args = parser.parse_args(argv)
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
    if args.command == "list":
        for item in load_catalog():
            print(item.id)
        return 0
    return 2


def _validate(*, include_drafts: bool = False) -> int:
    errors: list[str] = []
    workflows = load_catalog(include_drafts=include_drafts)
    for item in workflows:
        errors.extend(validate_workflow(item))
    errors.extend(validate_scenarios(workflows))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


def _sync(*, check: bool = False) -> int:
    workflows = load_catalog()
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    changed: list[Path] = []
    expected = {item.published_path for item in workflows}
    for item in workflows:
        if not item.published_path.exists() or not filecmp.cmp(
            item.workflow_path, item.published_path, shallow=False
        ):
            changed.append(item.published_path)
            if not check:
                shutil.copyfile(item.workflow_path, item.published_path)
        if _support_tree_changed(item.support_path, item.published_support_path):
            changed.append(item.published_support_path)
            if not check:
                _sync_support_tree(item.support_path, item.published_support_path)
    if check:
        stale_extra = sorted(
            path
            for path in PUBLISHED_DIR.glob("*.yaml")
            if path not in expected and not path.name.startswith("devflows-")
        )
        changed.extend(stale_extra)
    if changed:
        for path in changed:
            print(path, file=sys.stderr)
        return 1 if check else 0
    return 0


def _support_tree_changed(source: Path, destination: Path) -> bool:
    if not source.exists():
        return destination.exists()
    if not destination.exists():
        return True
    comparison = filecmp.dircmp(source, destination)
    return bool(
        comparison.left_only
        or comparison.right_only
        or comparison.diff_files
        or comparison.funny_files
        or any(
            _support_tree_changed(source / name, destination / name)
            for name in comparison.common_dirs
        )
    )


def _sync_support_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if source.exists():
        shutil.copytree(source, destination)


def _docs(*, check: bool = False) -> int:
    if check:
        with tempfile.TemporaryDirectory(prefix="devflows-docs-check-") as temporary_dir:
            write_generated_docs(load_catalog(), output_dir=Path(temporary_dir) / "reference")
        return 0

    changed = write_generated_docs(load_catalog())
    if changed:
        for path in changed:
            print(path, file=sys.stderr)
        return 1 if check else 0
    return 0


def _test_generate(*, check: bool = False) -> int:
    changed = write_generated_test_workflows(load_catalog(), check=check)
    if changed:
        for path in changed:
            print(path, file=sys.stderr)
        return 1 if check else 0
    return 0


def _test_local() -> int:
    return run_local_scenarios(load_catalog())


def _release_check() -> int:
    config_path = Path(".github/release-please/config.json")
    manifest_path = Path(".github/release-please/manifest.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    workflows = load_catalog()
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
        release_type = item.metadata.get("release", {}).get("type")
        if package_config.get("release-type") != release_type:
            errors.append(
                f"{config_path}: {package_path} release-type must match devflow release.type."
            )

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Release configuration is valid.")
    return 0
