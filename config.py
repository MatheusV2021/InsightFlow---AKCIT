"""Configurações centralizadas e caminhos locais da aplicação."""

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr

BASE_DIR = Path(__file__).resolve().parent
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_DOCUMENTS_PER_OPERATION = 3
MAX_PDF_PAGES = 10
MAX_ANALYSIS_DOCUMENTS = 3
MAX_ANALYSIS_TEXT_CHARS = 16000
MAX_LLM_INPUT_CHARS = 24000
MAX_LLM_OUTPUT_TOKENS = 4000
ANALYSIS_PIPELINE_VERSION = "1"
MAX_CHAT_QUESTION_CHARS = 1000
CHAT_CHUNK_CHARS = 1800
CHAT_CHUNK_OVERLAP = 200
MAX_CHAT_CHUNKS = 6
MAX_CHAT_CONTEXT_CHARS = 10000


class Settings(BaseModel):
    """Valida configurações sem exigir credenciais para iniciar a interface."""

    ai_provider: Literal["openai", "gemini"] = "openai"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(default="gemini-3.8-flash", min_length=1)
    gemini_embedding_model: str = Field(default="gemini-embedding-001", min_length=1)
    gemini_embedding_dimensions: int = Field(default=1536, ge=1, le=3072)
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = Field(default="gpt-4.1-mini", min_length=1)
    demo_mode: bool = False
    database_path: Path = BASE_DIR / "database" / "insightflow.db"
    uploads_dir: Path = BASE_DIR / "uploads"
    chat_retrieval: Literal["qdrant", "lexical"] = "qdrant"
    qdrant_path: Path = BASE_DIR / "database" / "qdrant"
    embedding_model: str = Field(default="text-embedding-3-small", min_length=1)
    embedding_dimensions: int = Field(default=1536, ge=1, le=3072)
    vector_score_threshold: float = Field(default=0.3, ge=-1, le=1)
    chat_agent_enabled: bool = True
    agent_max_tool_calls: int = Field(default=4, ge=1, le=8)
    agent_max_searches: int = Field(default=3, ge=1, le=6)

    @property
    def provider_label(self) -> str:
        return "Gemini" if self.ai_provider == "gemini" else "OpenAI"

    @property
    def generation_model(self) -> str:
        return self.gemini_model if self.ai_provider == "gemini" else self.openai_model

    @property
    def active_embedding_model(self) -> str:
        return self.gemini_embedding_model if self.ai_provider == "gemini" else self.embedding_model

    @property
    def active_embedding_dimensions(self) -> int:
        return self.gemini_embedding_dimensions if self.ai_provider == "gemini" else self.embedding_dimensions


def get_settings(env_file: Path = BASE_DIR / ".env") -> Settings:
    """Carrega o .env, dando prioridade às variáveis do processo."""
    values = dotenv_values(env_file)
    fields = {
        "AI_PROVIDER": "ai_provider",
        "GEMINI_API_KEY": "gemini_api_key",
        "GEMINI_MODEL": "gemini_model",
        "GEMINI_EMBEDDING_MODEL": "gemini_embedding_model",
        "GEMINI_EMBEDDING_DIMENSIONS": "gemini_embedding_dimensions",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_MODEL": "openai_model",
        "DEMO_MODE": "demo_mode",
        "CHAT_RETRIEVAL": "chat_retrieval",
        "QDRANT_PATH": "qdrant_path",
        "OPENAI_EMBEDDING_MODEL": "embedding_model",
        "OPENAI_EMBEDDING_DIMENSIONS": "embedding_dimensions",
        "VECTOR_SCORE_THRESHOLD": "vector_score_threshold",
        "CHAT_AGENT_ENABLED": "chat_agent_enabled",
        "AGENT_MAX_TOOL_CALLS": "agent_max_tool_calls",
        "AGENT_MAX_SEARCHES": "agent_max_searches",
    }
    config = {}
    for env_name, field_name in fields.items():
        value = os.environ.get(env_name, values.get(env_name))
        if value is not None:
            config[field_name] = value
    if "qdrant_path" in config:
        path = Path(config["qdrant_path"])
        config["qdrant_path"] = path if path.is_absolute() else BASE_DIR / path
    return Settings(**config)
