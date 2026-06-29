import pathlib

import pytest


@pytest.fixture(autouse=True)
def _dummy_openai_key(monkeypatch):
    """Most code paths read OPENAI_API_KEY; give tests a dummy so building the
    agent doesn't fail. No network call is ever made in the test suite."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")


@pytest.fixture
def example_csv() -> str:
    return str(pathlib.Path(__file__).parent.parent / "examples" / "example_costs.csv")
