from devflows.catalog import load_catalog
from devflows.scenarios import load_scenarios, render_test_workflow, validate_scenarios


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
    assert "Assert file exists: test/scenarios/pandoc/working-directory/output.html" in rendered
