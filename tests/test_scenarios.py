import dataclasses
import json
from pathlib import Path

import pytest

import devflows.publish as publish
from devflows.catalog import Workflow, load_catalog
from devflows.errors import DevflowsError
from devflows.scenarios import (
    _assert_job,
    _call_job,
    _ephemeral_branch_cleanup_job,
    _ephemeral_branch_setup_job,
    _find_validate_step,
    _missing_mutation_inputs,
    _required_call_permissions,
    _requires_write,
    _serialize_input_value,
    _setup_artifact_job,
    _validation_failure_env,
    _validation_failure_job,
    hosted_scenario_path,
    load_scenarios,
    local_scenario_path,
    render_test_workflow,
    validate_scenarios,
    write_generated_test_workflows,
)


def _with_scenarios(workflow_id: str, scenarios: list[dict]) -> Workflow:
    """A copy of a real catalog workflow whose scenarios are replaced for testing."""
    workflow = {item.id: item for item in load_catalog()}[workflow_id]
    metadata = dict(workflow.metadata)
    metadata["tests"] = {"scenarios": scenarios}
    return dataclasses.replace(workflow, metadata=metadata)


def _writeback_mutation_scenario(scenario_id: str, branch_prefix: str, runs=("hosted",)) -> dict:
    return {
        "id": scenario_id,
        "runs": list(runs),
        "mutation": {
            "type": "ephemeral-branch",
            "branch-prefix": branch_prefix,
            "fixture-path": ".fx",
            "initial-files": [{"path": "seed.html", "content": "seed"}],
        },
        "writeback-payload": {
            "artifact-name": "p",
            "paths": ["generated"],
            "files": [{"path": "generated/i.html", "content": "x"}],
            "delete-paths": [],
        },
        "assertions": [{"type": "branch-file-missing", "path": "z"}],
    }


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
    assert _required_call_permissions(workflows["devcontainer-build"]) == {
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


def test_call_job_grants_packages_write_for_devcontainer_build() -> None:
    job = _call_job(_scenario("devcontainer-build", "build-only-minimal"), runner="hosted")

    assert job["permissions"]["packages"] == "write"


# --- scenario secrets passthrough (devcontainer-run run-secrets) ---


def test_call_job_passes_scenario_secrets_to_the_reusable_workflow() -> None:
    # A scenario that declares `secrets:` has the call job forward them under
    # `secrets:` so the reusable workflow receives GitHub-masked values.
    job = _call_job(
        _scenario("devcontainer-run", "run-secrets-into-hooks-and-command"), runner="hosted"
    )

    assert job["secrets"] == {"run-secrets": '{"DEVFLOWS_TEST_SECRET":"ok-123"}'}


def test_call_job_omits_secrets_when_scenario_declares_none() -> None:
    job = _call_job(_scenario("devcontainer-run", "hooks-and-exec"), runner="hosted")

    assert "secrets" not in job


def test_scenario_secrets_are_loaded_as_a_mapping() -> None:
    scenario = _scenario("devcontainer-run", "run-secrets-into-hooks-and-command")

    assert scenario.secrets == {"run-secrets": '{"DEVFLOWS_TEST_SECRET":"ok-123"}'}


def test_hosted_secrets_scenario_renders_secrets_block() -> None:
    rendered = render_test_workflow(
        load_scenarios(load_catalog()),
        runner="hosted",
        name="Hosted",
    )

    assert "devcontainer_run_run_secrets_into_hooks_and_command_call" in rendered
    assert "run-secrets:" in rendered


def test_scenario_secrets_must_be_declared_by_the_target_workflow() -> None:
    workflow = _with_scenarios(
        "devcontainer-run",
        [
            {
                "id": "bad-secret-name",
                "runs": ["hosted"],
                "inputs": {"devcontainer-image": "alpine:3.20", "run-command": "echo hi"},
                "secrets": {"not-declared": "x"},
                "assertions": [{"type": "file-glob-exists", "path": "r.txt"}],
                "artifact": {"name": "a"},
            }
        ],
    )
    errors = validate_scenarios([workflow])

    assert any("not declared" in error and "not-declared" in error for error in errors)


def test_validation_failure_scenario_cannot_declare_secrets() -> None:
    workflow = _with_scenarios(
        "devcontainer-run",
        [
            {
                "id": "vf-with-secret",
                "runs": ["hosted"],
                "expect": "validation-failure",
                "inputs": {"devcontainer-image": "alpine:bad:ref", "run-command": "echo hi"},
                "secrets": {"run-secrets": "x"},
            }
        ],
    )
    errors = validate_scenarios([workflow])

    assert any("cannot declare secrets" in error for error in errors)


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


def test_writeback_payload_upload_includes_hidden_files() -> None:
    """The writeback payload's files/ subtree holds dotfiles (e.g. .devflows-e2e/),
    which upload-artifact v4+ drops by default -- apply-payload then fails with
    "Payload file is missing or invalid". Regression guard for PR #5 run
    29072401089: the setup upload must opt into hidden files."""
    job = _ephemeral_branch_setup_job(_scenario("writeback", "ephemeral-branch-writeback"))
    upload = next(step for step in job["steps"] if step["name"] == "Upload writeback payload")

    assert upload["with"]["include-hidden-files"] is True


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
    assert len(_missing_mutation_inputs(workflows["devcontainer-build"])) == 4


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


def test_devcontainer_build_has_build_only_scenario() -> None:
    build = [
        scenario
        for scenario in load_scenarios(load_catalog())
        if scenario.workflow.id == "devcontainer-build"
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


# --- item 2: fork-safe gating of write-requiring hosted call jobs ---


def test_requires_write_true_for_all_promoted_workflows() -> None:
    for wf_id in ("pandoc", "writeback", "devcontainer-build"):
        scenario = next(s for s in load_scenarios(load_catalog()) if s.workflow.id == wf_id)
        assert _requires_write(scenario)


def test_hosted_call_jobs_are_fork_gated() -> None:
    rendered = render_test_workflow(load_scenarios(load_catalog()), runner="hosted", name="H")

    # Elevated call jobs are skipped on fork PRs, kept for same-repo PRs.
    assert "github.event.pull_request.head.repo.full_name == github.repository" in rendered
    # Assert jobs still use always() so they observe a same-repo call's result,
    # but AND-combine the fork guard so they skip when the call was skipped.
    assert (
        "always() && (github.event_name != 'pull_request' "
        "|| github.event.pull_request.head.repo.full_name == github.repository)"
    ) in rendered


def test_hosted_workflow_documents_fork_limitation() -> None:
    rendered = render_test_workflow(load_scenarios(load_catalog()), runner="hosted", name="H")

    assert rendered.startswith("# GENERATED by devflows test-generate")
    assert "fork pull requests skip" in rendered


# --- item 19: stricter mutation-scenario validation ---


def test_mutation_scenario_cannot_run_locally() -> None:
    writeback = _workflows()["writeback"]
    metadata = dict(writeback.metadata)
    metadata["tests"] = {
        "scenarios": [_writeback_mutation_scenario("mut", "p/one", runs=("local", "hosted"))]
    }
    workflow = dataclasses.replace(writeback, metadata=metadata)

    errors = validate_scenarios([workflow])

    assert any("cannot run locally" in error for error in errors)


def test_duplicate_mutation_branch_prefix_rejected() -> None:
    writeback = _workflows()["writeback"]
    metadata = dict(writeback.metadata)
    metadata["tests"] = {
        "scenarios": [
            _writeback_mutation_scenario("mut-a", "shared/prefix"),
            _writeback_mutation_scenario("mut-b", "shared/prefix"),
        ]
    }
    workflow = dataclasses.replace(writeback, metadata=metadata)

    errors = validate_scenarios([workflow])

    assert any("unique across mutation scenarios" in error for error in errors)


def test_mutation_requires_nonempty_initial_files() -> None:
    writeback = _workflows()["writeback"]
    metadata = dict(writeback.metadata)
    scenario = _writeback_mutation_scenario("mut", "p/one")
    scenario["mutation"]["initial-files"] = []
    metadata["tests"] = {"scenarios": [scenario]}
    workflow = dataclasses.replace(writeback, metadata=metadata)

    errors = validate_scenarios([workflow])

    assert any("initial-files must be nonempty" in error for error in errors)


# --- item 21: local scenario workflow is act-only ---


def test_local_workflow_has_act_guard() -> None:
    rendered = render_test_workflow(load_scenarios(load_catalog()), runner="local", name="L")

    assert "require_act:" in rendered
    assert "task scenarios-local" in rendered
    assert '"${ACT:-}" != "true"' in rendered


def test_success_scenario_assert_job_uses_always_and_success_result() -> None:
    # Success path: assert-result.py checks for the default "success" result and
    # the assert job stays on always() (no EXPECTED_RESULT env of the removed
    # continue-on-error mechanism).
    scenario = _scenario("pandoc", "markdown-html-artifact")

    assert_job = _assert_job(scenario, runner="hosted")

    assert assert_job["if"] == "always()"
    result_step = next(
        step for step in assert_job["steps"] if "assert-result.py" in step.get("run", "")
    )
    assert "EXPECTED_RESULT" not in result_step["env"]


# --- file-glob-exists assertion ---


def test_file_glob_exists_assert_step_sets_glob_flag() -> None:
    # The real python-build cibw scenario asserts a *manylinux* wheel with a glob,
    # because auditwheel makes the exact filename non-deterministic.
    scenario = _scenario("python-build", "cibw-manylinux")

    assert_job = _assert_job(scenario, runner="hosted")
    glob_step = next(step for step in assert_job["steps"] if "matches glob" in step["name"])

    assert glob_step["env"]["ASSERT_GLOB"] == "1"
    # The glob is joined under the downloaded-artifact path, and the wildcard is
    # preserved for the harness to expand.
    assert glob_step["env"]["ASSERT_PATH"].endswith(
        "devflows_cext_fixture-0.1.0-cp313-cp313-*manylinux*.whl"
    )
    assert "assert-file-exists.py" in glob_step["run"]


def test_file_glob_exists_is_accepted_and_requires_path() -> None:
    ok = _with_scenarios(
        "pandoc",
        [
            {
                "id": "glob-ok",
                "runs": ["hosted"],
                "inputs": {},
                "artifact": {"name": "a"},
                "assertions": [{"type": "file-glob-exists", "path": "out/*.whl"}],
            }
        ],
    )
    assert validate_scenarios([ok]) == []

    missing_path = _with_scenarios(
        "pandoc",
        [
            {
                "id": "glob-nopath",
                "runs": ["hosted"],
                "inputs": {},
                "artifact": {"name": "a"},
                "assertions": [{"type": "file-glob-exists"}],
            }
        ],
    )
    errors = validate_scenarios([missing_path])
    assert any("file-glob-exists assertions require path" in error for error in errors)


def test_hosted_file_glob_assertion_requires_artifact_metadata() -> None:
    # file-glob-exists is a file assertion, so a hosted scenario using it must
    # declare artifact metadata (the assert job downloads it before globbing).
    workflow = _with_scenarios(
        "pandoc",
        [
            {
                "id": "glob-noartifact",
                "runs": ["hosted"],
                "inputs": {},
                "assertions": [{"type": "file-glob-exists", "path": "out/*.whl"}],
            }
        ],
    )
    errors = validate_scenarios([workflow])
    assert any("hosted file assertions require artifact metadata" in error for error in errors)


# --- expect: validation-failure scenarios (validate-script harness) ---
#
# Promoted catalog workflows do not (yet) expose an inputs-only validate step:
# devcontainer-build's validate env references secrets.* and writeback has no
# validate step, so both are correctly rejected by the harness (see the
# rejection tests below). The mechanism is therefore exercised against this
# synthetic fixture; the five incoming Python workflows adopt the same shape at
# integration.

_INPUTS_ONLY_VALIDATE_ENV = {
    "MODE": "${{ inputs.mode }}",
    "COUNT": "${{ inputs.count }}",
    "STRICT": "${{ inputs.strict }}",
    # Dropped by the harness (it runs the script by its checkout path).
    "DEVFLOWS_SCRIPT_ROOT": "${{ steps.devflows-runtime.outputs.script-root }}",
}


def _validation_fixture(
    scenarios: list[dict], *, validate_env=None, with_validate=True
) -> Workflow:
    """A synthetic reusable workflow with an inputs-only validate step."""
    env = _INPUTS_ONLY_VALIDATE_ENV if validate_env is None else validate_env
    if with_validate:
        jobs = {
            "validate": {
                "name": "Validate inputs",
                "runs-on": "ubuntu-latest",
                "steps": [
                    {
                        "name": "Validate inputs",
                        "shell": "bash",
                        "env": env,
                        "run": 'python "${DEVFLOWS_SCRIPT_ROOT}/vf-demo/validate-inputs.py"',
                    }
                ],
            }
        }
    else:
        jobs = {"run": {"name": "Run", "runs-on": "ubuntu-latest", "steps": [{"run": "echo hi"}]}}
    workflow = {
        "name": "[Reusable]: VF Demo",
        "on": {
            "workflow_call": {
                "inputs": {
                    "mode": {"type": "string", "required": True},
                    "count": {"type": "number", "required": False, "default": 3},
                    "strict": {"type": "boolean", "required": False, "default": False},
                }
            }
        },
        "jobs": jobs,
    }
    metadata = {
        "id": "vf-demo",
        "name": "VF Demo",
        "status": "active",
        "release": {"type": "simple", "major": 0},
        "tests": {"scenarios": scenarios},
    }
    return Workflow(
        id="vf-demo",
        path=Path("tests/fixtures/vf-demo"),
        workflow_path=Path("tests/fixtures/vf-demo/workflow.yaml"),
        metadata_path=Path("tests/fixtures/vf-demo/devflow.yaml"),
        metadata=metadata,
        workflow=workflow,
    )


def _vf_scenario(scenario_id: str = "bad-mode", *, message: str | None = None, **overrides) -> dict:
    scenario = {
        "id": scenario_id,
        "runs": ["local", "hosted"],
        "expect": "validation-failure",
        "inputs": {"mode": "nope"},
    }
    if message is not None:
        scenario["failure-message-contains"] = message
    scenario.update(overrides)
    return scenario


def test_serialize_input_value_matches_github_presentation() -> None:
    assert _serialize_input_value(True) == "true"
    assert _serialize_input_value(False) == "false"
    assert _serialize_input_value(3) == "3"
    assert _serialize_input_value(2.0) == "2"
    assert _serialize_input_value(1.5) == "1.5"
    assert _serialize_input_value(None) == ""
    assert _serialize_input_value("pandoc/core:3.8") == "pandoc/core:3.8"


def test_validation_failure_env_fills_from_inputs_and_defaults() -> None:
    workflow = _validation_fixture([_vf_scenario(inputs={"mode": "nope"})])
    scenario = load_scenarios([workflow])[0]

    env = _validation_failure_env(scenario)

    # Scenario input wins; unset inputs fall back to the workflow defaults, all
    # serialized as GitHub presents them to ${{ inputs.* }} (booleans/numbers as
    # strings). The runtime script-root entry is dropped, not reconstructed.
    assert env == {"MODE": "nope", "COUNT": "3", "STRICT": "false"}


def test_validation_failure_env_serializes_bool_and_number_overrides() -> None:
    scenario_dict = _vf_scenario(inputs={"mode": "full", "count": 5, "strict": True})
    workflow = _validation_fixture([scenario_dict])
    scenario = load_scenarios([workflow])[0]

    env = _validation_failure_env(scenario)

    assert env == {"MODE": "full", "COUNT": "5", "STRICT": "true"}


def test_validation_failure_job_runs_validate_script_and_no_call() -> None:
    workflow = _validation_fixture([_vf_scenario(message="mode must be one of")])
    scenario = load_scenarios([workflow])[0]

    hosted = _validation_failure_job(scenario, runner="hosted")

    # A plain job: no reusable-workflow `uses:`, no continue-on-error.
    assert "uses" not in hosted
    assert "continue-on-error" not in hosted
    steps = hosted["steps"]
    assert steps[0]["uses"].startswith("actions/checkout@")
    assert steps[0]["with"]["persist-credentials"] is False
    run_step = steps[-1]
    assert "assert-validation-failure.py" in run_step["run"]
    assert (
        run_step["env"]["DEVFLOWS_VALIDATE_SCRIPT"]
        == "tests/fixtures/vf-demo/scripts/validate-inputs.py"
    )
    assert run_step["env"]["DEVFLOWS_FAILURE_MESSAGE_CONTAINS"] == "mode must be one of"
    assert run_step["env"]["MODE"] == "nope"


def test_validation_failure_local_job_has_no_checkout() -> None:
    workflow = _validation_fixture([_vf_scenario()])
    scenario = load_scenarios([workflow])[0]

    local = _validation_failure_job(scenario, runner="local")

    # Local relies on act's bind mount; a checkout would clobber the workspace.
    assert all(not step.get("uses", "").startswith("actions/checkout@") for step in local["steps"])


def test_validation_failure_renders_for_both_runners_without_call_shape() -> None:
    workflow = _validation_fixture([_vf_scenario()])
    scenarios = load_scenarios([workflow])

    hosted = render_test_workflow(scenarios, runner="hosted", name="H")
    local = render_test_workflow(scenarios, runner="local", name="L")

    for rendered in (hosted, local):
        assert "vf_demo_bad_mode_validate:" in rendered
        # The broken continue-on-error-on-call shape must be gone everywhere.
        assert "continue-on-error" not in rendered
        assert "uses: ./.github/workflows/vf-demo.yaml" not in rendered


def test_no_shipped_scenario_emits_continue_on_error() -> None:
    scenarios = load_scenarios(load_catalog())

    for runner in ("hosted", "local"):
        rendered = render_test_workflow(scenarios, runner=runner, name="X")
        assert "continue-on-error" not in rendered


def test_validation_failure_scenario_is_valid() -> None:
    workflow = _validation_fixture([_vf_scenario()])

    assert validate_scenarios([workflow]) == []


def test_validation_failure_requires_discoverable_validate_step() -> None:
    workflow = _validation_fixture([_vf_scenario()], with_validate=False)

    assert _find_validate_step(workflow) is None
    errors = validate_scenarios([workflow])
    assert any("none was found" in error for error in errors)


def test_validation_failure_rejects_non_input_env_reference() -> None:
    env = {
        "MODE": "${{ inputs.mode }}",
        "TOKEN_SET": "${{ secrets.some-token != '' }}",
    }
    workflow = _validation_fixture([_vf_scenario()], validate_env=env)

    errors = validate_scenarios([workflow])

    assert any("secrets" in error and "TOKEN_SET" in error for error in errors)


def test_validation_failure_rejects_call_only_fields() -> None:
    scenario = _vf_scenario(
        assertions=[{"type": "file-exists", "path": "x"}],
        artifact={"name": "a"},
        cleanup=["x"],
    )
    workflow = _validation_fixture([scenario])

    errors = validate_scenarios([workflow])

    assert any("cannot declare assertions" in error for error in errors)
    assert any("cannot declare artifact" in error for error in errors)
    assert any("cannot declare cleanup" in error for error in errors)


def test_failure_message_contains_only_valid_with_validation_failure() -> None:
    scenario = {
        "id": "sc",
        "runs": ["hosted"],
        "inputs": {},
        "failure-message-contains": "boom",
        "assertions": [{"type": "workflow-output-equals", "name": "o", "value": "v"}],
    }
    workflow = _with_scenarios("pandoc", [scenario])

    errors = validate_scenarios([workflow])

    assert any("failure-message-contains is only valid" in error for error in errors)


def test_promoted_workflows_without_inputs_only_validate_are_rejected() -> None:
    # devcontainer-build has a validate step but its env references secrets.*;
    # writeback has no validate step. Both must be rejected so the mechanism
    # never silently generates an incomplete env.
    catalog = {item.id: item for item in load_catalog()}

    bdc = _with_scenarios(
        "devcontainer-build",
        [{"id": "nb", "runs": ["hosted"], "expect": "validation-failure", "inputs": {}}],
    )
    assert _find_validate_step(catalog["devcontainer-build"]) is not None
    assert any("references" in error for error in validate_scenarios([bdc]))

    wb = _with_scenarios(
        "writeback",
        [{"id": "nv", "runs": ["hosted"], "expect": "validation-failure", "inputs": {}}],
    )
    assert _find_validate_step(catalog["writeback"]) is None
    assert any("none was found" in error for error in validate_scenarios([wb]))


# --- setup-artifact binary payloads (source-path / content-base64) ---


def _setup_scenario(files: list[dict]) -> dict:
    return {
        "id": "setup-bin",
        "runs": ["hosted"],
        "inputs": {"artifact-download-enabled": True},
        "setup-artifact": {"name": "n", "path": "p", "files": files},
        "assertions": [{"type": "workflow-output-equals", "name": "o", "value": "v"}],
    }


def test_setup_artifact_job_passes_source_path_and_base64_verbatim() -> None:
    files = [
        {"path": "wheelhouse/pkg.whl", "source-path": "tests/scenarios/x/pkg.whl"},
        {"path": "wheelhouse/data.bin", "content-base64": "AAECAw=="},
    ]
    workflow = _with_scenarios("pandoc", [_setup_scenario(files)])
    scenario = load_scenarios([workflow])[0]

    job = _setup_artifact_job(scenario)
    create_step = next(
        step for step in job["steps"] if "create-setup-files.py" in step.get("run", "")
    )
    passed = json.loads(create_step["env"]["DEVFLOWS_SETUP_FILES"])

    assert passed[0]["source-path"] == "tests/scenarios/x/pkg.whl"
    assert passed[1]["content-base64"] == "AAECAw=="


def test_setup_artifact_file_requires_exactly_one_source() -> None:
    workflow = _with_scenarios(
        "pandoc",
        [_setup_scenario([{"path": "a", "content": "x", "source-path": "b"}])],
    )

    errors = validate_scenarios([workflow])

    assert any(
        "must set exactly one of content, source-path, content-base64" in error for error in errors
    )


def test_setup_artifact_source_path_rejects_traversal() -> None:
    workflow = _with_scenarios(
        "pandoc",
        [_setup_scenario([{"path": "a", "source-path": "../escape.whl"}])],
    )

    errors = validate_scenarios([workflow])

    assert any("source-path must be a workspace-relative path" in error for error in errors)


def test_setup_artifact_source_path_scenario_is_valid() -> None:
    workflow = _with_scenarios(
        "pandoc",
        [_setup_scenario([{"path": "a/pkg.whl", "source-path": "tests/scenarios/x/pkg.whl"}])],
    )

    assert validate_scenarios([workflow]) == []


def test_every_local_job_depends_on_require_act() -> None:
    from devflows.yaml import load_yaml_text

    rendered = render_test_workflow(load_scenarios(load_catalog()), runner="local", name="L")
    # Strip the leading comment header before parsing.
    workflow = load_yaml_text(rendered)
    jobs = workflow["jobs"]
    assert "require_act" in jobs
    for job_id, job in jobs.items():
        if job_id == "require_act":
            continue
        needs = job.get("needs")
        needs_list = [needs] if isinstance(needs, str) else list(needs or [])
        assert "require_act" in needs_list, job_id


# --- per-workflow scenario file split + size guard ---


def test_scenario_path_helpers_name_per_workflow_files() -> None:
    assert hosted_scenario_path("pandoc") == Path(
        ".github/workflows/devflows-scenarios-pandoc.yaml"
    )
    assert local_scenario_path("pandoc") == Path(
        ".github/workflows/devflows-scenarios-pandoc.local.yaml"
    )


def test_write_splits_into_per_workflow_files_and_drops_monolith(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("devflows.scenarios.SCENARIOS_DIR", tmp_path)

    changed = write_generated_test_workflows(load_catalog())

    # One hosted file per workflow with hosted scenarios; a local file only when the
    # workflow also owns local scenarios (devcontainer-build/writeback have none).
    assert (tmp_path / "devflows-scenarios-pandoc.yaml").exists()
    assert (tmp_path / "devflows-scenarios-pandoc.local.yaml").exists()
    assert (tmp_path / "devflows-scenarios-devcontainer-build.yaml").exists()
    assert not (tmp_path / "devflows-scenarios-devcontainer-build.local.yaml").exists()
    assert not (tmp_path / "devflows-scenarios-writeback.local.yaml").exists()
    # The retired monolithic files are never (re)produced.
    assert not (tmp_path / "devflows-scenarios.yaml").exists()
    assert not (tmp_path / "devflows-local-scenarios.yaml").exists()
    # Every emitted file names exactly its owning workflow's scenarios.
    pandoc = (tmp_path / "devflows-scenarios-pandoc.yaml").read_text(encoding="utf-8")
    assert "pandoc_markdown_html_artifact_call" in pandoc
    assert "zenodo" not in pandoc
    assert set(changed) == set(tmp_path.glob("devflows-scenarios-*.yaml"))


def test_write_prunes_retired_monolithic_and_stale_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("devflows.scenarios.SCENARIOS_DIR", tmp_path)
    # Seed the retired monolithic files plus a stale per-workflow file for a workflow
    # that no longer exists; all three must be pruned by a regeneration.
    stale = [
        tmp_path / "devflows-scenarios.yaml",
        tmp_path / "devflows-local-scenarios.yaml",
        tmp_path / "devflows-scenarios-removed-workflow.yaml",
    ]
    for path in stale:
        path.write_text("# stale\n", encoding="utf-8")

    changed = write_generated_test_workflows(load_catalog())

    for path in stale:
        assert not path.exists()
        assert path in changed


def test_write_check_mode_flags_stale_without_touching_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("devflows.scenarios.SCENARIOS_DIR", tmp_path)
    orphan = tmp_path / "devflows-scenarios.yaml"
    orphan.write_text("# stale\n", encoding="utf-8")

    changed = write_generated_test_workflows(load_catalog(), check=True)

    # check mode reports the drift (new files missing + orphan present) but writes
    # and deletes nothing.
    assert orphan in changed
    assert orphan.exists()
    assert not (tmp_path / "devflows-scenarios-pandoc.yaml").exists()


def test_scenario_files_are_size_guarded(tmp_path, monkeypatch) -> None:
    # A future workflow with huge scenarios must fail generation locally rather than
    # startup-fail on a hosted run. Shrinking the shared cap makes the real catalog's
    # per-workflow files trip the same guard published workflows use.
    monkeypatch.setattr(publish, "MAX_GENERATED_WORKFLOW_BYTES", 500)

    with pytest.raises(DevflowsError) as excinfo:
        write_generated_test_workflows(load_catalog(), check=True)

    message = str(excinfo.value)
    assert "over the 500-byte cap" in message
    # The guard labels the offending file, not a catalog workflow id.
    assert "devflows-scenarios-" in message


def test_scenario_files_are_size_guarded_in_write_mode(tmp_path, monkeypatch) -> None:
    # WRITE mode (devflows test-generate without --check) must trip the same cap as
    # --check, so an oversized file fails generation locally instead of writing a
    # startup-failing workflow. The guard fires before any file is written.
    monkeypatch.setattr("devflows.scenarios.SCENARIOS_DIR", tmp_path)
    monkeypatch.setattr(publish, "MAX_GENERATED_WORKFLOW_BYTES", 500)

    with pytest.raises(DevflowsError) as excinfo:
        write_generated_test_workflows(load_catalog(), check=False)

    assert "over the 500-byte cap" in str(excinfo.value)
    # Fail-closed: nothing was written to disk before the guard raised.
    assert list(tmp_path.glob("devflows-scenarios-*.yaml")) == []
