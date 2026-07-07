from devflows.catalog import load_catalog


def test_github_actions_on_key_is_not_boolean() -> None:
    workflow = load_catalog()[0].workflow

    assert "on" in workflow
    assert True not in workflow
