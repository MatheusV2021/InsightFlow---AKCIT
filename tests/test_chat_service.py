"""Busca e respostas documentais com SQLite real e chamadas de IA simuladas."""

import json
from unittest.mock import Mock, patch

import pytest
from openai import APIConnectionError

from config import CHAT_CHUNK_CHARS, MAX_CHAT_CHUNKS, MAX_CHAT_CONTEXT_CHARS, MAX_CHAT_QUESTION_CHARS
from database import repository
from database.db import get_connection
from models.schemas import ChatModelOutput, ChatStatement, Evidence
from services.chat_service import (
    INSUFFICIENT_EVIDENCE, ask_question, retrieve_relevant_chunks,
    revalidate_response_sources, tokenize,
)
from services.document_service import process_document
from services.llm_service import LLMError


@pytest.fixture
def chat_documents(document_settings, make_pdf):
    texts = [
        ("Contrato Alfa: pagamento em 30 dias.", "A confidencialidade deve ser preservada."),
        ("Contrato Beta: pagamento em 60 dias.",),
        ("O inventario possui cadeiras e mesas.",),
    ]
    documents = [process_document(document_settings, f"document-{index}.pdf", make_pdf(pages))
                 for index, pages in enumerate(texts)]
    return documents, texts


def make_output(document, quote, text="O contrato prevê pagamento no prazo informado.", page_number=1):
    return ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(
        text=text, evidence=[Evidence(document_id=document.id, filename=document.original_filename,
                                      page_number=page_number, quote=quote)],
    )])


def test_lexical_search_normalizes_accents_case_and_simple_plurals():
    assert tokenize("Quais CONTRATOS possuem prazos de pagamento?") == ["contrato", "prazo", "pagamento"]
    assert tokenize("obrigações obrigação") == ["obrigacao", "obrigacao"]
    assert tokenize("CONFIDENCIALIDADE 30") == ["confidencialidade", "30"]


def test_search_uses_selected_documents_and_preserves_page(document_settings, chat_documents):
    documents, _ = chat_documents
    chunks, _ = retrieve_relevant_chunks(document_settings, "Qual a confidencialidade?", [documents[0].id])
    assert len(chunks) == 1
    assert chunks[0].document_id == documents[0].id
    assert chunks[0].page_number == 2
    assert "confidencialidade" in chunks[0].text
    assert not repository.get_selected_document_pages(document_settings.database_path, [])
    assert not repository.get_selected_document_pages(document_settings.database_path, ["' OR 1=1 --"])


def test_search_ranking_and_ties_are_deterministic(document_settings, chat_documents):
    documents, _ = chat_documents
    ids = [document.id for document in documents]
    chunks, _ = retrieve_relevant_chunks(document_settings, "contratos pagamento", ids)
    reversed_chunks, _ = retrieve_relevant_chunks(document_settings, "pagamento contratos", list(reversed(ids)))
    assert chunks == reversed_chunks
    assert [source.document_id for source in chunks] == sorted(document.id for document in documents[:2])
    assert all(source.document_id != documents[2].id for source in chunks)


@pytest.mark.parametrize("ids", [[], ["nonexistent"]])
def test_empty_or_missing_document_selection_makes_no_call(document_settings, ids):
    with patch("services.chat_service.request_structured") as model:
        with pytest.raises(ValueError):
            ask_question(document_settings, "Qual o pagamento?", ids)
        model.assert_not_called()


@pytest.mark.parametrize("question", ["", "  ", "x" * (MAX_CHAT_QUESTION_CHARS + 1)])
def test_question_limits_are_checked_before_api(document_settings, chat_documents, question):
    documents, _ = chat_documents
    with patch("services.chat_service.request_structured") as model:
        with pytest.raises(ValueError):
            ask_question(document_settings, question, [documents[0].id])
        model.assert_not_called()


@pytest.mark.parametrize("question", ["Qual a temperatura de Marte?", "e o de?"])
def test_no_matching_terms_returns_clear_message_without_model(document_settings, chat_documents, question):
    documents, _ = chat_documents
    with patch("services.chat_service.request_structured") as model:
        response = ask_question(document_settings, question, [documents[0].id])
        model.assert_not_called()
    assert response.answer == INSUFFICIENT_EVIDENCE
    assert not response.evidence


def test_scan_and_partial_document_have_coverage_warnings(document_settings, make_pdf):
    document = process_document(document_settings, "scan.pdf", make_pdf(("",) * 11))
    with patch("services.chat_service.request_structured") as model:
        response = ask_question(document_settings, "Quais pagamentos?", [document.id])
        model.assert_not_called()
    assert response.answer == INSUFFICIENT_EVIDENCE
    assert len(response.warnings) == 2


def test_context_size_and_number_of_chunks_are_limited(document_settings, chat_documents):
    documents, _ = chat_documents
    with get_connection(document_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ?", ("pagamento contrato prazo " * 1000,))
    chunks, warnings = retrieve_relevant_chunks(document_settings, "pagamento", [document.id for document in documents])
    assert len(chunks) <= MAX_CHAT_CHUNKS
    assert sum(len(chunk.text) for chunk in chunks) <= MAX_CHAT_CONTEXT_CHARS
    assert all(len(chunk.text) <= CHAT_CHUNK_CHARS for chunk in chunks)
    assert any("limites de contexto" in warning for warning in warnings)


def test_answer_has_verified_document_page_and_question_in_payload(document_settings, chat_documents):
    documents, texts = chat_documents
    output = make_output(documents[0], texts[0][0])
    with patch("services.chat_service.request_structured", return_value=output) as model:
        response = ask_question(document_settings, "Qual o pagamento?", [documents[0].id])
        model.assert_called_once()
        payload = json.loads(model.call_args.args[2])
        assert payload["question"] == "Qual o pagamento?"
        assert all(item["document_id"] == documents[0].id for item in payload["excerpts"])
        assert model.call_args.args[3] is ChatModelOutput
    assert "[1]" in response.answer
    assert response.evidence == output.statements[0].evidence
    assert response.evidence[0].page_number == 1


@pytest.mark.parametrize(("field", "value"), [
    ("document_id", "unknown"), ("filename", "wrong.pdf"),
    ("page_number", 2), ("quote", "A made-up quote"), ("quote", "   "),
])
def test_invalid_sources_hide_the_entire_answer(document_settings, chat_documents, field, value):
    documents, texts = chat_documents
    output = make_output(documents[0], texts[0][0], text="This ungrounded answer must never appear.")
    setattr(output.statements[0].evidence[0], field, value)
    with patch("services.chat_service.request_structured", return_value=output):
        response = ask_question(document_settings, "Qual o pagamento?", [documents[0].id])
    assert response.answer == INSUFFICIENT_EVIDENCE
    assert not response.evidence
    assert "ungrounded" not in response.model_dump_json()


@pytest.mark.parametrize("output", [
    ChatModelOutput(sufficient_evidence=False, statements=[]),
    ChatModelOutput(sufficient_evidence=True, statements=[]),
    ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(text="Unverified claim", evidence=[])]),
])
def test_response_without_evidence_is_not_presented_as_grounded(document_settings, chat_documents, output):
    documents, _ = chat_documents
    with patch("services.chat_service.request_structured", return_value=output):
        response = ask_question(document_settings, "Qual o pagamento?", [documents[0].id])
    assert response.answer == INSUFFICIENT_EVIDENCE
    assert not response.evidence


def test_quote_on_page_not_in_retrieved_chunk_is_rejected(document_settings, chat_documents):
    documents, _ = chat_documents
    with get_connection(document_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ? WHERE document_id = ? AND page_number = ?",
                           ("pagamento " + "x" * 4000 + "Unsent evidence", documents[0].id, 1))
    output = make_output(documents[0], "Unsent evidence")
    with patch("services.chat_service.request_structured", return_value=output):
        response = ask_question(document_settings, "pagamento", [documents[0].id])
    assert not response.evidence


def test_multiple_chunks_of_same_page_validate_and_repeated_source_is_deduplicated(document_settings, chat_documents):
    documents, _ = chat_documents
    text = "pagamento em 30 dias. " + "x " * 1000 + "pagamento em 60 dias."
    with get_connection(document_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ? WHERE document_id = ? AND page_number = ?", (text, documents[0].id, 1))
    first = make_output(documents[0], "pagamento em 30 dias.").statements[0]
    second = make_output(documents[0], "pagamento em 60 dias.").statements[0]
    with patch("services.chat_service.request_structured", return_value=ChatModelOutput(
        sufficient_evidence=True, statements=[first, second, first]
    )):
        response = ask_question(document_settings, "pagamento", [documents[0].id])
    assert len(response.evidence) == 2
    assert response.answer.count("[1]") == 2
    assert "[2]" in response.answer


def test_connection_failure_is_sanitized_via_shared_sdk_client(document_settings, chat_documents):
    documents, _ = chat_documents
    settings = document_settings.model_copy()
    from pydantic import SecretStr
    settings.openai_api_key = SecretStr("fake-test-key")
    with patch("services.llm_service.OpenAI") as client:
        client.return_value.__enter__.return_value.responses.parse.side_effect = APIConnectionError(request=Mock())
        with pytest.raises(LLMError, match="conectar"):
            ask_question(settings, "pagamento", [documents[0].id])


def test_history_response_sources_are_rechecked_without_calling_model(document_settings, chat_documents):
    documents, texts = chat_documents
    with patch("services.chat_service.request_structured", return_value=make_output(documents[0], texts[0][0])):
        response = ask_question(document_settings, "pagamento", [documents[0].id])
    with get_connection(document_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ? WHERE document_id = ?", ("Changed source", documents[0].id))
    with patch("services.chat_service.request_structured") as model:
        checked = revalidate_response_sources(document_settings, response)
        model.assert_not_called()
    assert checked.answer == INSUFFICIENT_EVIDENCE
    assert not checked.evidence


def test_chat_page_two_questions_history_and_reruns(document_settings, chat_documents):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR

    documents, texts = chat_documents
    output = make_output(documents[0], texts[0][0])
    with patch("config.get_settings", return_value=document_settings), patch(
        "services.chat_service.request_structured", return_value=output
    ) as model:
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/assistant.py").run()
        assert app.chat_input[0].disabled
        app.multiselect[0].set_value([documents[0].id]).run()
        assert not app.chat_input[0].disabled
        model.assert_not_called()
        app.chat_input[0].set_value("Qual o prazo de pagamento?").run()
        assert not app.exception
        assert not app.error
        assert len(app.get("chat_message")) == 2
        assert model.call_count == 1
        assert any(documents[0].original_filename in caption.value and "página 1" in caption.value for caption in app.caption)
        assert len([expander for expander in app.expander if "Fontes verificadas" in expander.label]) == 1
        app.run()
        assert model.call_count == 1
        app.chat_input[0].set_value("O que o contrato menciona sobre pagamento?").run()
        assert not app.exception
        assert len(app.get("chat_message")) == 4
        assert model.call_count == 2
        app.switch_page("pages/dashboard.py").run()
        app.switch_page("pages/assistant.py").run()
        assert not app.exception
        assert len(app.get("chat_message")) == 4
        assert model.call_count == 2


def test_chat_page_missing_key_is_shown_and_not_retried(document_settings, chat_documents):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR

    documents, _ = chat_documents
    with patch("config.get_settings", return_value=document_settings):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/assistant.py").run()
        app.multiselect[0].set_value([documents[0].id]).run()
        app.chat_input[0].set_value("pagamento").run()
        assert not app.exception
        assert len(app.error) == 1
        assert "OPENAI_API_KEY" in app.error[0].value
        app.run()
        assert not app.exception
        assert len(app.get("chat_message")) == 2


def test_chat_page_no_evidence_does_not_show_source_expander(document_settings, chat_documents):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR

    documents, _ = chat_documents
    with patch("config.get_settings", return_value=document_settings), patch("services.chat_service.request_structured") as model:
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/assistant.py").run()
        app.multiselect[0].set_value([documents[0].id]).run()
        app.chat_input[0].set_value("Qual a temperatura de Marte?").run()
        assert not app.exception
        assert INSUFFICIENT_EVIDENCE in [text.value for text in app.text]
        assert not any("Fontes verificadas" in expander.label for expander in app.expander)
        model.assert_not_called()
