from devflows.cli import _release_check


def test_release_config_is_valid() -> None:
    assert _release_check() == 0
