"""Qdrant real em disco e embeddings simulados, sem tráfego externo."""

from unittest.mock import Mock, patch
from contextlib import closing

import pytest
from qdrant_client import QdrantClient

from database.db import get_connection
from models.schemas import ChatModelOutput, ChatStatement, Evidence
from services.chat_service import ask_question, retrieve_relevant_chunks, INSUFFICIENT_EVIDENCE
from services.document_service import process_document
from services.llm_service import LLMError
from services.vector_service import collection_name


@pytest.fixture
def vector_settings(document_settings):
    return document_settings.model_copy(update={"chat_retrieval": "qdrant", "embedding_dimensions": 3})


@pytest.fixture
def embeddings(monkeypatch):
    def encode(settings, texts):
        # Vetores conhecidos: penalidade e multa têm o mesmo significado, sem termo comum.
        return [[1.0, 0.0, 0.0] if any(term in text.lower() for term in ("multa", "penalidade"))
                else [0.0, 1.0, 0.0] for text in texts]
    mock = Mock(side_effect=encode)
    monkeypatch.setattr("services.vector_service.embed_texts", mock)
    return mock


def test_semantic_retrieval_persists_and_filters_selection(vector_settings, make_pdf, embeddings):
    first = process_document(vector_settings, "primeiro.pdf", make_pdf(("Multa de 10 reais.",)))
    other = process_document(vector_settings, "outro.pdf", make_pdf(("Multa de 500 reais.",)))
    chunks, _ = retrieve_relevant_chunks(vector_settings, "Qual a penalidade?", [first.id])
    assert len(chunks) == 1 and chunks[0].document_id == first.id
    assert "10 reais" in chunks[0].text
    assert embeddings.call_count == 2  # indexação + pergunta
    retrieve_relevant_chunks(vector_settings, "Qual a penalidade?", [first.id])
    assert embeddings.call_count == 3  # reabre o banco e reutiliza o índice
    retrieve_relevant_chunks(vector_settings, "Qual a penalidade?", [other.id])
    chunks, _ = retrieve_relevant_chunks(vector_settings, "Qual a penalidade?", [first.id])
    assert all(chunk.document_id == first.id for chunk in chunks)
    with closing(QdrantClient(path=str(vector_settings.qdrant_path))) as client:
        assert client.count(collection_name(vector_settings)).count == 2


def test_changed_and_empty_pages_remove_stale_vectors(vector_settings, make_pdf, embeddings):
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Multa antiga.",)))
    retrieve_relevant_chunks(vector_settings, "penalidade", [doc.id])
    with get_connection(vector_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ?", ("Multa nova.",))
    chunks, _ = retrieve_relevant_chunks(vector_settings, "penalidade", [doc.id])
    assert chunks[0].text == "Multa nova."
    with closing(QdrantClient(path=str(vector_settings.qdrant_path))) as client:
        assert client.count(collection_name(vector_settings)).count == 1
    with get_connection(vector_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ''")
    chunks, _ = retrieve_relevant_chunks(vector_settings, "penalidade", [doc.id])
    assert not chunks
    with closing(QdrantClient(path=str(vector_settings.qdrant_path))) as client:
        assert client.count(collection_name(vector_settings)).count == 0


def test_vector_answer_still_rejects_invented_sources(vector_settings, make_pdf, embeddings):
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Multa de 10 reais.",)))
    output = ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(
        text="Multa de 100 reais.", evidence=[Evidence(document_id=doc.id, filename="doc.pdf",
                                                       page_number=1, quote="Multa de 100 reais.")])])
    with patch("services.chat_service.request_structured", return_value=output):
        response = ask_question(vector_settings, "Qual a penalidade?", [doc.id])
    assert response.answer == INSUFFICIENT_EVIDENCE and not response.evidence


def test_below_threshold_does_not_generate_answer(vector_settings, make_pdf, embeddings):
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Cadeiras e mesas.",)))
    with patch("services.chat_service.request_structured") as model:
        response = ask_question(vector_settings, "penalidade", [doc.id])
        model.assert_not_called()
    assert response.answer == INSUFFICIENT_EVIDENCE


def test_demo_never_opens_vector_index(vector_settings, make_pdf, embeddings):
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Multa contratual.",)))
    vector_settings.demo_mode = True
    response = ask_question(vector_settings, "multa", [doc.id])
    assert response.is_demo and response.evidence
    embeddings.assert_not_called()
    assert not vector_settings.qdrant_path.exists()


def test_failed_indexing_is_retryable(vector_settings, make_pdf, embeddings):
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Multa contratual.",)))
    original = embeddings.side_effect
    embeddings.side_effect = LLMError("Falha simulada")
    with pytest.raises(LLMError):
        ask_question(vector_settings, "penalidade", [doc.id])
    embeddings.side_effect = original
    chunks, _ = retrieve_relevant_chunks(vector_settings, "penalidade", [doc.id])
    assert chunks


def test_vector_answer_accepts_valid_sources_and_rechecks_sqlite(vector_settings, make_pdf, embeddings):
    from services.chat_service import revalidate_response_sources
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Multa de 10 reais.",)))
    output = ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(
        text="A penalidade é de 10 reais.", evidence=[Evidence(document_id=doc.id, filename="doc.pdf",
                                                             page_number=1, quote="Multa de 10 reais.")])])
    with patch("services.chat_service.request_structured", return_value=output):
        response = ask_question(vector_settings, "Qual a penalidade?", [doc.id])
    assert response.evidence and "[1]" in response.answer
    with get_connection(vector_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = 'Texto modificado'")
    assert revalidate_response_sources(vector_settings, response).answer == INSUFFICIENT_EVIDENCE


def test_context_limits_and_deleted_document_cleanup(vector_settings, make_pdf, embeddings):
    from config import MAX_CHAT_CHUNKS, MAX_CHAT_CONTEXT_CHARS
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Multa contratual.",)))
    deleted = process_document(vector_settings, "removido.pdf", make_pdf(("Multa antiga.",)))
    retrieve_relevant_chunks(vector_settings, "penalidade", [deleted.id])
    with get_connection(vector_settings.database_path) as connection:
        connection.execute("DELETE FROM documents WHERE id = ?", (deleted.id,))
        connection.execute("UPDATE document_pages SET extracted_text = ?", ("Multa contratual. " * 1000,))
    chunks, warnings = retrieve_relevant_chunks(vector_settings, "penalidade", [doc.id])
    assert len(chunks) <= MAX_CHAT_CHUNKS
    assert sum(len(chunk.text) for chunk in chunks) <= MAX_CHAT_CONTEXT_CHARS
    assert warnings
    with closing(QdrantClient(path=str(vector_settings.qdrant_path))) as client:
        records, _ = client.scroll(collection_name(vector_settings), limit=100)
        assert all(record.payload["document_id"] == doc.id for record in records)


def test_model_changes_use_separate_collection(vector_settings):
    assert collection_name(vector_settings) != collection_name(
        vector_settings.model_copy(update={"embedding_model": "another-model"}))
    assert collection_name(vector_settings) != collection_name(
        vector_settings.model_copy(update={"embedding_dimensions": 2}))


def test_locked_store_has_friendly_error(vector_settings, make_pdf, embeddings):
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Multa contratual.",)))
    with closing(QdrantClient(path=str(vector_settings.qdrant_path))):
        with pytest.raises(LLMError, match="outra instância"):
            retrieve_relevant_chunks(vector_settings, "penalidade", [doc.id])


def test_vector_chat_page_reuses_index_and_does_not_call_on_rerun(vector_settings, make_pdf, embeddings):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR
    doc = process_document(vector_settings, "doc.pdf", make_pdf(("Multa de 10 reais.",)))
    output = ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(
        text="A penalidade é de 10 reais.", evidence=[Evidence(document_id=doc.id, filename="doc.pdf",
                                                             page_number=1, quote="Multa de 10 reais.")])])
    with patch("config.get_settings", return_value=vector_settings), patch(
        "services.chat_service.request_structured", return_value=output
    ) as model:
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/assistant.py").run()
        app.multiselect[0].set_value([doc.id]).run()
        embeddings.assert_not_called()
        app.chat_input[0].set_value("Qual a penalidade?").run()
        assert not app.exception and not app.error
        assert embeddings.call_count == 2 and model.call_count == 1
        app.run()
        assert embeddings.call_count == 2 and model.call_count == 1
        app.chat_input[0].set_value("Qual a penalidade contratual?").run()
        assert not app.exception and not app.error
        assert embeddings.call_count == 3 and model.call_count == 2
