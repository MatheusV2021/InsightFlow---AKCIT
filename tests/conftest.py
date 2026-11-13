"""Fixtures de PDFs sintéticos em memória, sem documentos corporativos."""

import pymupdf
import pytest
from unittest.mock import Mock

from config import Settings
from services.document_service import initialize_workspace


@pytest.fixture(autouse=True)
def prevent_real_openai_calls(monkeypatch):
    """Falha imediatamente se um teste tentar instanciar o cliente real."""
    monkeypatch.setattr(
        "services.llm_service.OpenAI",
        Mock(side_effect=AssertionError("Chamadas reais à OpenAI são proibidas nos testes.")),
    )


@pytest.fixture
def make_pdf():
    def build(texts=("First page",)):
        with pymupdf.open() as pdf:
            for text in texts:
                page = pdf.new_page()
                if text:
                    page.insert_text((72, 72), text)
            return pdf.tobytes()

    return build


@pytest.fixture
def document_settings(tmp_path):
    settings = Settings(
        database_path=tmp_path / "database" / "test.db",
        uploads_dir=tmp_path / "uploads",
    )
    initialize_workspace(settings)
    return settings
