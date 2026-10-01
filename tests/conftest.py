import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Use a temp issue log and never call external APIs during tests."""
    monkeypatch.setattr(config, "ISSUES_FILE", tmp_path / "issues.json")
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", None)
    monkeypatch.setattr(config, "REDIS_REST_URL", None)
    monkeypatch.setattr(config, "REDIS_REST_TOKEN", None)


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)
