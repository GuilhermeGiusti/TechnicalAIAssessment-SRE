import pathlib

import pytest

from cost_analyst import config as cfg


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """Keep the suite hermetic: `load_config` calls `load_dotenv()`, which would
    otherwise pull a developer's real `agent/.env` into the environment and
    pollute env-precedence/gating tests (e.g. a local CSV_PATH defeating the
    'missing CSV_PATH raises' test). Neutralize it so tests only see what they
    set via monkeypatch."""
    monkeypatch.setattr(cfg, "_load_dotenv", lambda: None)


@pytest.fixture(autouse=True)
def _dummy_openai_key(monkeypatch):
    """Most code paths read OPENAI_API_KEY; give tests a dummy so building the
    agent doesn't fail. No network call is ever made in the test suite."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")


@pytest.fixture
def example_csv() -> str:
    return str(pathlib.Path(__file__).parent.parent / "examples" / "example_costs.csv")
