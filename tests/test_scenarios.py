import dataclasses

from devflows.catalog import Workflow, load_catalog
from devflows.scenarios import (
    _assert_job,
    _call_job,
    _ephemeral_branch_cleanup_job,
    _missing_mutation_inputs,
    _required_call_permissions,
    _setup_artifact_job,
    load_scenarios,
    render_test_workflow,
    validate_scenarios,
)


def _workflows() -> dict[str, Workflow]:
    return {item.id: item for item in load_catalog()}


def _scenario(workflow_id: str, scenario_id: str):
    for scenario in load_scenarios(load_catalog()):
        if scenario.workflow.id == workflow_id and scenario.id == scenario_id:
            return scenario
    raise KeyError(f"{workflow_id}/{scenario_id}")


def test_scenarios_are_valid() -> None:
    workflows = load_catalog()

    assert validate_scenarios(workflows) == []


def test_pandoc_has_multiple_scenarios() -> None:
    scenarios = load_scenarios(load_catalog())
    pandoc_scenarios = [scenario for scenario in scenarios if scenario.workflow.id == "pandoc"]

    assert [scenario.id for scenario in pandoc_scenarios] == [
        "markdown-html-local",
        "markdown-html-artifact",
        "working-directory-local",
        "working-directory-artifact",
        "artifact-download-html",
    ]


def test_writeback_has_ephemeral_branch_scenario() -> None:
    scenarios = load_scenarios(load_catalog())
    writeback_scenarios = [
        scenario for scenario in scenarios if scenario.workflow.id == "writeback"
    ]

    assert [scenario.id for scenario in writeback_scenarios] == ["ephemeral-branch-writeback"]
    assert writeback_scenarios[0].mutation["type"] == "ephemeral-branch"


def test_hosted_scenario_workflow_downloads_artifacts_and_asserts_files() -> None:
    rendered = render_test_workflow(
        load_scenarios(load_catalog()),
        runner="hosted",
        name="Hosted",
    )

    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in rendered
    assert "pandoc_markdown_html_artifact_call" in rendered
    assert "artifact-upload-enabled: true" in rendered
    assert "artifact-upload-name: pandoc-markdown-html" in rendered
    assert "pandoc_artifact_download_html_setup" in rendered
    assert "pandoc-input-markdown" in rendered
    assert "artifact-download-enabled: true" in rendered
    assert "Assert file contains: example.html" in rendered
    assert "Pandoc Working Directory" in rendered
    assert "writeback_ephemeral_branch_writeback_setup" in rendered
    assert "writeback_ephemeral_branch_writeback_cleanup" in rendered
    assert "github.event_name != 'pull_request'" in rendered
    assert "contents: write" in rendered
    assert "writeback-e2e-payload" in rendered
    assert "branch-file-missing" in rendered


def test_local_scenario_workflow_cleans_outputs_and_asserts_files() -> None:
    rendered = render_test_workflow(
        load_scenarios(load_catalog()),
        runner="local",
        name="Local",
    )

    assert "pandoc_markdown_html_local_clean" in rendered
    assert "rm -rf .devflows-test/pandoc/markdown-html-local" in rendered
    assert "checkout-enabled: false" in rendered
    assert "Assert file exists: tests/scenarios/pandoc/working-directory/output.html" in rendered


# --- task 1: call jobs grant the permissions the called workflow declares ---


def test_required_call_permissions_unions_declared_permissions() -> None:
    workflows = _workflows()

    assert _required_call_permissions(workflows["pandoc"]) == {
        "actions": "read",
        "contents": "write",
    }
    assert _required_call_permissions(workflows["writeback"]) == {
        "actions": "read",
        "contents": "write",
    }
    assert _required_call_permissions(workflows["build-devcontainer"]) == {
        "actions": "read",
        "contents": "read",
        "packages": "write",
    }


def test_call_job_grants_writeback_permissions_even_when_read_only() -> None:
    # The read-only pandoc artifact scenario still calls pandoc.yaml, whose
    # published form embeds a commit job requesting contents: write. Without the
    # grant GitHub startup-fails the whole run.
    job = _call_job(_scenario("pandoc", "markdown-html-artifact"), runner="hosted")

    assert job["permissions"] == {"actions": "read", "contents": "write"}


def test_call_job_grants_packages_write_for_build_devcontainer() -> None:
    job = _call_job(_scenario("build-devcontainer", "build-only-minimal"), runner="hosted")

    assert job["permissions"]["packages"] == "write"


# --- task 2: hosted setup/assert jobs check out before running any script ---


def test_hosted_assert_job_checks_out_before_scripts() -> None:
    job = _assert_job(_scenario("pandoc", "markdown-html-artifact"), runner="hosted")
    steps = job["steps"]

    assert steps[0]["uses"].startswith("actions/checkout@")
    assert steps[0]["with"]["persist-credentials"] is False
    first_script = next(
        index for index, step in enumerate(steps) if "harness/scenarios" in step.get("run", "")
    )
    assert first_script > 0


def test_local_assert_job_has_no_checkout() -> None:
    # Local runs rely on act's bind mount; a checkout would clobber the workspace.
    job = _assert_job(_scenario("pandoc", "markdown-html-local"), runner="local")

    assert all(not step.get("uses", "").startswith("actions/checkout@") for step in job["steps"])


def test_setup_artifact_job_checks_out_first() -> None:
    job = _setup_artifact_job(_scenario("pandoc", "artifact-download-html"))

    assert job["steps"][0]["uses"].startswith("actions/checkout@")
    assert job["steps"][0]["with"]["persist-credentials"] is False


def test_mutation_assert_job_checks_out_before_assert_result() -> None:
    job = _assert_job(_scenario("writeback", "ephemeral-branch-writeback"), runner="hosted")
    steps = job["steps"]

    assert steps[0]["name"] == "Checkout ephemeral branch"
    assert steps[1]["name"] == "Assert scenario succeeded"
    assert "harness/scenarios" not in steps[0].get("run", "")


# --- task 3/4: scripts come from harness/, not the removed generated copies ---


def test_scenarios_reference_harness_scripts_only() -> None:
    rendered = render_test_workflow(load_scenarios(load_catalog()), runner="hosted", name="H")

    assert "python harness/scenarios/assert-result.py" in rendered
    assert ".github/workflows/devflows-scenarios/" not in rendered
    assert ".github/workflows/writeback/create-payload.py" not in rendered


# --- task 5a: duplicate scenario ids are a validation error ---


def test_duplicate_scenario_ids_are_rejected() -> None:
    pandoc = _workflows()["pandoc"]
    metadata = dict(pandoc.metadata)
    metadata["tests"] = {
        "scenarios": [
            {
                "id": "dup",
                "runs": ["local"],
                "inputs": {"checkout-enabled": False},
                "cleanup": ["a"],
                "assertions": [{"type": "file-exists", "path": "a"}],
            },
            {
                "id": "dup",
                "runs": ["local"],
                "inputs": {"checkout-enabled": False},
                "cleanup": ["b"],
                "assertions": [{"type": "file-exists", "path": "b"}],
            },
        ]
    }
    workflow = dataclasses.replace(pandoc, metadata=metadata)

    errors = validate_scenarios([workflow])

    assert any("duplicate scenario id" in error for error in errors)


# --- task 5b: mutation validation generalizes beyond the writeback workflow ---


def test_missing_mutation_inputs_generalizes_beyond_writeback() -> None:
    workflows = _workflows()

    assert _missing_mutation_inputs(workflows["writeback"]) == []
    assert "writeback-artifact-name" in _missing_mutation_inputs(workflows["pandoc"])
    assert len(_missing_mutation_inputs(workflows["build-devcontainer"])) == 4


def test_mutation_scenario_rejected_for_workflow_without_writeback_inputs() -> None:
    pandoc = _workflows()["pandoc"]
    metadata = dict(pandoc.metadata)
    metadata["tests"] = {
        "scenarios": [
            {
                "id": "mut",
                "runs": ["hosted"],
                "mutation": {
                    "type": "ephemeral-branch",
                    "branch-prefix": "x/y",
                    "fixture-path": ".x",
                    "initial-files": [],
                },
                "writeback-payload": {
                    "artifact-name": "p",
                    "paths": [],
                    "files": [],
                    "delete-paths": [],
                },
                "assertions": [{"type": "branch-file-missing", "path": "z"}],
            }
        ]
    }
    workflow = dataclasses.replace(pandoc, metadata=metadata)

    errors = validate_scenarios([workflow])

    assert any("writeback-artifact-name" in error for error in errors)


# --- task 5c: cleanup keys on the deterministic branch prefix, not an output ---


def test_cleanup_job_keys_on_deterministic_branch_prefix() -> None:
    job = _ephemeral_branch_cleanup_job(_scenario("writeback", "ephemeral-branch-writeback"))
    delete_step = job["steps"][-1]

    assert delete_step["env"] == {"DEVFLOWS_BRANCH_PREFIX": "devflows/e2e/writeback"}
    assert "needs." not in str(delete_step["env"])


# --- task 6: coverage additions ---


def test_build_devcontainer_has_build_only_scenario() -> None:
    build = [
        scenario
        for scenario in load_scenarios(load_catalog())
        if scenario.workflow.id == "build-devcontainer"
    ]

    assert [scenario.id for scenario in build] == ["build-only-minimal"]
    assert build[0].inputs["devcontainer-push"] == "never"
    assert build[0].inputs["merge-enabled"] is False
    assert build[0].inputs["docker-login-enabled"] is False


def test_writeback_scenario_exercises_absent_deletion() -> None:
    writeback = _scenario("writeback", "ephemeral-branch-writeback")

    assert "absent-on-branch.html" in writeback.writeback_payload["delete-paths"]
    assert any(
        assertion.get("path") == "absent-on-branch.html"
        and assertion.get("type") == "branch-file-missing"
        for assertion in writeback.assertions
    )
