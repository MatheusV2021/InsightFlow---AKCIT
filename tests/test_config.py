"""Verificações de configuração local e variáveis de ambiente."""

import pytest
from pydantic import ValidationError

from config import BASE_DIR, get_settings


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "DEMO_MODE"):
        monkeypatch.delenv(name, raising=False)


def test_startup_defaults_without_env_or_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = get_settings(tmp_path / "missing.env")
    assert settings.openai_api_key.get_secret_value() == ""
    assert settings.demo_mode is False
    assert settings.database_path == BASE_DIR / "database" / "insightflow.db"


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DEMO_MODE=true\nOPENAI_MODEL=file-model\nOPENAI_API_KEY=test-value\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    settings = get_settings(env_file)
    assert settings.demo_mode is False
    assert settings.openai_model == "environment-model"
    assert settings.openai_api_key.get_secret_value() == "test-value"
    assert "test-value" not in repr(settings)


def test_invalid_boolean_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "invalid")
    with pytest.raises(ValidationError):
        get_settings(tmp_path / "missing.env")
