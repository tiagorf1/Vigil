import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--integration", action="store_true", default=False,
        help="run integration tests that need live OpenAlice + Kronos",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(reason="needs --integration (live services)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
