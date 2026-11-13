"""Verificações de configuração local e variáveis de ambiente."""

import pytest
from pydantic import ValidationError

from config import BASE_DIR, get_settings


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "DEMO_MODE", "CHAT_RETRIEVAL",
                 "QDRANT_PATH", "OPENAI_EMBEDDING_MODEL", "OPENAI_EMBEDDING_DIMENSIONS",
                 "VECTOR_SCORE_THRESHOLD", "CHAT_AGENT_ENABLED", "AGENT_MAX_TOOL_CALLS", "AGENT_MAX_SEARCHES",
                 "AI_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_EMBEDDING_MODEL", "GEMINI_EMBEDDING_DIMENSIONS"):
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


def test_vector_settings_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("QDRANT_PATH", "database/custom-vectors")
    monkeypatch.setenv("VECTOR_SCORE_THRESHOLD", "0.45")
    settings = get_settings(tmp_path / "missing.env")
    assert settings.chat_retrieval == "qdrant"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.qdrant_path == BASE_DIR / "database/custom-vectors"
    assert settings.vector_score_threshold == 0.45
    assert settings.chat_agent_enabled is True
    assert settings.agent_max_tool_calls == 4 and settings.agent_max_searches == 3


@pytest.mark.parametrize(("name", "value"), [
    ("CHAT_RETRIEVAL", "invalid"), ("OPENAI_EMBEDDING_DIMENSIONS", "0"),
    ("VECTOR_SCORE_THRESHOLD", "2"),
    ("CHAT_AGENT_ENABLED", "invalid"), ("AGENT_MAX_TOOL_CALLS", "0"),
    ("AGENT_MAX_TOOL_CALLS", "9"), ("AGENT_MAX_SEARCHES", "0"), ("AGENT_MAX_SEARCHES", "7"),
    ("AI_PROVIDER", "invalid"), ("GEMINI_MODEL", ""), ("GEMINI_EMBEDDING_DIMENSIONS", "0"),
])
def test_invalid_vector_settings_are_rejected(monkeypatch, tmp_path, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        get_settings(tmp_path / "missing.env")


def test_agent_environment_overrides_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("CHAT_AGENT_ENABLED=true\nAGENT_MAX_TOOL_CALLS=4\nAGENT_MAX_SEARCHES=3\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_AGENT_ENABLED", "false")
    monkeypatch.setenv("AGENT_MAX_TOOL_CALLS", "2")
    monkeypatch.setenv("AGENT_MAX_SEARCHES", "1")
    settings = get_settings(env_file)
    assert not settings.chat_agent_enabled
    assert settings.agent_max_tool_calls == 2 and settings.agent_max_searches == 1


def test_gemini_settings_select_separate_key_models_and_dimensions(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("AI_PROVIDER=gemini\nGEMINI_API_KEY=private-test\nGEMINI_MODEL=gemini-file\n"
                        "GEMINI_EMBEDDING_MODEL=gemini-embedding-001\nGEMINI_EMBEDDING_DIMENSIONS=768\n"
                        "OPENAI_EMBEDDING_DIMENSIONS=1536\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-environment")
    settings = get_settings(env_file)
    assert settings.ai_provider == "gemini" and settings.provider_label == "Gemini"
    assert settings.generation_model == "gemini-environment"
    assert settings.active_embedding_model == "gemini-embedding-001"
    assert settings.active_embedding_dimensions == 768
    assert settings.gemini_api_key.get_secret_value() == "private-test"
    assert "private-test" not in repr(settings)
    assert settings.openai_api_key.get_secret_value() == ""
