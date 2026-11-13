"""Configurações centralizadas e caminhos locais da aplicação."""

import os
from pathlib import Path

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

    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = Field(default="gpt-4.1-mini", min_length=1)
    demo_mode: bool = False
    database_path: Path = BASE_DIR / "database" / "insightflow.db"
    uploads_dir: Path = BASE_DIR / "uploads"


def get_settings(env_file: Path = BASE_DIR / ".env") -> Settings:
    """Carrega o .env, dando prioridade às variáveis do processo."""
    values = dotenv_values(env_file)
    fields = {
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_MODEL": "openai_model",
        "DEMO_MODE": "demo_mode",
    }
    config = {}
    for env_name, field_name in fields.items():
        value = os.environ.get(env_name, values.get(env_name))
        if value is not None:
            config[field_name] = value
    return Settings(**config)
