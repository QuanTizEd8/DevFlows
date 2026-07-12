from __future__ import annotations

from devflows.propagation import (
    package_prefix,
    propagation_violations,
    published_workflow_path,
)

WORKFLOWS = ["pandoc", "writeback", "devcontainer-build"]


def test_no_change_no_violation() -> None:
    assert propagation_violations(["README.md", "docs/index.md"], WORKFLOWS) == []


def test_source_and_published_change_is_clean() -> None:
    # A normal per-workflow change: the source under workflows/<id>/ and its
    # regenerated published output move together, so release-please attributes it.
    changed = [
        "workflows/pandoc/workflow.yaml",
        published_workflow_path("pandoc"),
    ]
    assert propagation_violations(changed, WORKFLOWS) == []


def test_shared_change_without_package_touch_is_flagged() -> None:
    # A pure generator change regenerates published outputs but touches no package.
    changed = [
        "src/devflows/publish.py",
        published_workflow_path("pandoc"),
        published_workflow_path("writeback"),
    ]
    violations = propagation_violations(changed, WORKFLOWS)
    assert len(violations) == 2
    assert any("pandoc" in message for message in violations)
    assert any("writeback" in message for message in violations)
    assert all(package_prefix("devcontainer-build") not in message for message in violations)


def test_partial_propagation_flags_only_unpropagated() -> None:
    # pandoc got its scoped source change; writeback did not.
    changed = [
        "src/devflows/actions.py",
        "workflows/pandoc/devflow.yaml",
        published_workflow_path("pandoc"),
        published_workflow_path("writeback"),
    ]
    violations = propagation_violations(changed, WORKFLOWS)
    assert len(violations) == 1
    assert "writeback" in violations[0]
    assert published_workflow_path("writeback") in violations[0]


def test_nested_script_change_counts_as_package_touch() -> None:
    changed = [
        "workflows/devcontainer-build/scripts/merge-manifest.py",
        published_workflow_path("devcontainer-build"),
    ]
    assert propagation_violations(changed, WORKFLOWS) == []


def test_formatting_only_change_is_not_a_violation() -> None:
    # A shared re-render (e.g. a YAML dumper width change) alters the published
    # bytes for a workflow with no source change, but the predicate reports it as
    # semantically unchanged, so it must NOT be flagged.
    changed = [
        "src/devflows/yaml.py",
        published_workflow_path("pandoc"),
    ]
    violations = propagation_violations(
        changed,
        WORKFLOWS,
        published_semantically_changed=lambda wid: False,
    )
    assert violations == []


def test_semantic_change_is_still_flagged() -> None:
    # A shared change that DOES alter parsed meaning (predicate True) with no
    # source touch is still a genuine propagation violation.
    changed = [
        "src/devflows/publish.py",
        published_workflow_path("pandoc"),
    ]
    violations = propagation_violations(
        changed,
        WORKFLOWS,
        published_semantically_changed=lambda wid: True,
    )
    assert len(violations) == 1
    assert "pandoc" in violations[0]
