"""Ferramentas documentais limitadas, Qdrant real e respostas de IA simuladas."""

import json
from unittest.mock import Mock, patch

import pytest
from pydantic import SecretStr

from config import MAX_CHAT_CHUNKS, MAX_CHAT_CONTEXT_CHARS
from database import repository
from database.db import get_connection
from models.schemas import ChatModelOutput, ChatStatement, Evidence
from services.agent_service import investigate_question
from services.chat_service import INSUFFICIENT_EVIDENCE, ask_question, revalidate_response_sources
from services.document_service import process_document
from services.llm_service import LLMError


def tool(name, arguments, call_id="call_1"):
    return [{"type": "function_call", "name": name, "arguments": json.dumps(arguments), "call_id": call_id}]


@pytest.fixture
def agent_settings(document_settings):
    return document_settings.model_copy(update={
        "chat_retrieval": "qdrant", "chat_agent_enabled": True, "embedding_dimensions": 3,
    })


@pytest.fixture
def agent_documents(agent_settings, make_pdf):
    first = process_document(agent_settings, "contrato.pdf", make_pdf(("Multa de 10 reais.", "Excecao: aviso previo de 5 dias.")))
    other = process_document(agent_settings, "outro.pdf", make_pdf(("Informacao fora da selecao.",)))
    return first, other


@pytest.fixture
def embeddings(monkeypatch):
    mock = Mock(side_effect=lambda settings, texts: [[1.0, 0.0, 0.0] for _ in texts])
    monkeypatch.setattr("services.vector_service.embed_texts", mock)
    return mock


def output_for(doc, quote="Excecao: aviso previo de 5 dias.", page=2):
    return ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(
        text="Há uma exceção que exige aviso prévio.", evidence=[Evidence(
            document_id=doc.id, filename=doc.original_filename, page_number=page, quote=quote,
        )],
    )])


def test_agent_searches_reads_page_and_returns_verified_answer(agent_settings, agent_documents, embeddings):
    first, _ = agent_documents
    decisions = [tool("search_documents", {"query": "penalidade", "document_ids": [first.id]}),
                 tool("read_page", {"document_id": first.id, "page_number": 2, "offset": 0}, "call_2"), []]
    with patch("services.agent_service.request_tool_turn", side_effect=decisions) as planner, patch(
        "services.chat_service.request_structured", return_value=output_for(first)
    ) as generation:
        response = ask_question(agent_settings, "Qual a penalidade e suas exceções?", [first.id])
        assert planner.call_count == 3 and generation.call_count == 1
        assert response.evidence and "[1]" in response.answer
        payload = json.loads(generation.call_args.args[2])
        assert all(source["document_id"] == first.id for source in payload["excerpts"])
        assert any(source["page_number"] == 2 for source in payload["excerpts"])
    assert embeddings.call_count == 2  # indexação e uma busca
    assert any("1 busca(s)" in warning and "1 consulta(s)" in warning for warning in response.warnings)
    with get_connection(agent_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = 'Alterado' WHERE document_id = ?", (first.id,))
    assert revalidate_response_sources(agent_settings, response).answer == INSUFFICIENT_EVIDENCE


def test_page_tool_returns_sqlite_text_not_pdf(agent_settings, agent_documents):
    first, _ = agent_documents
    with get_connection(agent_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = 'Inicio: texto atualizado' WHERE document_id = ?", (first.id,))
    with patch("services.agent_service.request_tool_turn", side_effect=[
        tool("read_page", {"document_id": first.id, "page_number": 1, "offset": 8}), [],
    ]):
        sources, _ = investigate_question(agent_settings, "Leia", [first.id])
    assert sources[0].text == "texto atualizado"
    assert sources[0].filename == first.original_filename


@pytest.mark.parametrize("name,arguments", [
    ("read_page", {"document_id": "outside", "page_number": 1, "offset": 0}),
    ("search_documents", {"query": "texto", "document_ids": ["outside"]}),
    ("read_page", {"document_id": "selected", "page_number": -1, "offset": 0}),
    ("read_page", {"document_id": "selected", "page_number": 1, "offset": -1}),
    ("read_page", {"document_id": "selected", "page_number": "1", "offset": 0}),
    ("search_documents", {"query": " ", "document_ids": ["selected"]}),
    ("search_documents", {"query": "texto", "document_ids": []}),
    ("run_command", {"command": "anything"}),
])
def test_invalid_or_outside_calls_never_access_storage(agent_settings, agent_documents, name, arguments):
    first, _ = agent_documents
    arguments = {key: first.id if value == "selected" else [first.id] if value == ["selected"] else value
                 for key, value in arguments.items()}
    with patch("services.agent_service.request_tool_turn", side_effect=[tool(name, arguments), []]), patch(
        "services.agent_service.retrieve_vector_chunks"
    ) as search, patch("services.agent_service.repository.get_source_page") as read:
        sources, warnings = investigate_question(agent_settings, "Consulta", [first.id])
        search.assert_not_called()
        read.assert_not_called()
    assert not sources and any("recusada" in warning for warning in warnings)


def test_search_cap_is_enforced_even_if_model_ignores_removed_tool(agent_settings, agent_documents):
    first, _ = agent_documents
    agent_settings.agent_max_searches = 1
    decisions = [tool("search_documents", {"query": query, "document_ids": [first.id]}, f"call_{i}")
                 for i, query in enumerate(["multa", "penalidade", "excecao", "prazo"])]
    with patch("services.agent_service.request_tool_turn", side_effect=decisions) as planner, patch(
        "services.agent_service.retrieve_vector_chunks", return_value=([], [])
    ) as search:
        _, warnings = investigate_question(agent_settings, "Investigue", [first.id])
        assert planner.call_count == 4 and search.call_count == 1
        assert all(item["name"] != "search_documents" for item in planner.call_args.args[3])
    assert any("limite de chamadas" in warning for warning in warnings)


def test_repeated_calls_consume_budget_without_reexecuting(agent_settings, agent_documents):
    first, _ = agent_documents
    with patch("services.agent_service.request_tool_turn", return_value=tool(
        "read_page", {"document_id": first.id, "page_number": 99, "offset": 0}
    )) as planner, patch("services.agent_service.repository.get_source_page", return_value=None) as read:
        sources, warnings = investigate_question(agent_settings, "Investigue", [first.id])
    assert not sources and read.call_count == 1
    assert planner.call_count == agent_settings.agent_max_tool_calls
    assert any("limite de chamadas" in warning for warning in warnings)


def test_reformulates_after_empty_search(agent_settings, agent_documents):
    first, _ = agent_documents
    page = repository.get_source_page(agent_settings.database_path, first.id, 1)
    with patch("services.agent_service.request_tool_turn", side_effect=[
        tool("search_documents", {"query": "penalidade", "document_ids": [first.id]}),
        tool("search_documents", {"query": "multa", "document_ids": [first.id]}, "call_2"), [],
    ]), patch("services.agent_service.retrieve_vector_chunks", side_effect=[([], []), ([page], [])]) as search:
        sources, _ = investigate_question(agent_settings, "Investigue", [first.id])
    assert sources == [page] and search.call_count == 2


def test_agent_does_not_turn_unverified_planner_text_into_answer(agent_settings, agent_documents):
    first, _ = agent_documents
    with patch("services.agent_service.request_tool_turn", return_value=[{
        "type": "message", "content": [{"type": "output_text", "text": "Resposta sem fonte."}],
    }]), patch("services.chat_service.request_structured") as generation:
        response = ask_question(agent_settings, "Pergunta", [first.id])
        generation.assert_not_called()
    assert response.answer == INSUFFICIENT_EVIDENCE and not response.evidence


def test_agent_rejects_quote_not_in_sent_page_slice(agent_settings, agent_documents):
    first, _ = agent_documents
    text = "Inicio. " + "x" * 5000 + "Citação não enviada."
    with get_connection(agent_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ? WHERE document_id = ? AND page_number = 1", (text, first.id))
    with patch("services.agent_service.request_tool_turn", side_effect=[
        tool("read_page", {"document_id": first.id, "page_number": 1, "offset": 0}), [],
    ]), patch("services.chat_service.request_structured", return_value=output_for(first, "Citação não enviada.", 1)):
        response = ask_question(agent_settings, "O que consta?", [first.id])
    assert response.answer == INSUFFICIENT_EVIDENCE and not response.evidence


def test_combined_tools_respect_global_context_budget(agent_settings, agent_documents):
    first, _ = agent_documents
    with get_connection(agent_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ? WHERE document_id = ?",
                           ("a" * 4000 + "b" * 4000 + "c" * 4000, first.id))
    decisions = [tool("read_page", {"document_id": first.id, "page_number": 1, "offset": offset}, f"c_{offset}")
                 for offset in [0, 4000, 8000, 10000]]
    with patch("services.agent_service.request_tool_turn", side_effect=decisions):
        sources, warnings = investigate_question(agent_settings, "Leia tudo", [first.id])
    assert sum(len(source.text) for source in sources) == MAX_CHAT_CONTEXT_CHARS
    assert len(sources) <= MAX_CHAT_CHUNKS
    assert any("contexto" in warning for warning in warnings)


def test_demo_and_disabled_agent_keep_existing_flow(agent_settings, agent_documents):
    first, _ = agent_documents
    agent_settings.demo_mode = True
    with patch("services.agent_service.request_tool_turn") as planner:
        response = ask_question(agent_settings, "multa", [first.id])
        planner.assert_not_called()
    assert response.is_demo and response.evidence
    agent_settings.demo_mode = False
    agent_settings.chat_agent_enabled = False
    with patch("services.agent_service.request_tool_turn") as planner, patch(
        "services.chat_service.retrieve_vector_chunks", return_value=([], [])
    ):
        ask_question(agent_settings, "multa", [first.id])
        planner.assert_not_called()


@pytest.mark.parametrize("question,ids", [("", []), ("texto", ["missing"]), ("texto", [])])
def test_bad_input_stops_before_agent(agent_settings, question, ids):
    with patch("services.agent_service.request_tool_turn") as planner:
        with pytest.raises(ValueError):
            ask_question(agent_settings, question, ids)
        planner.assert_not_called()


def test_model_failure_does_not_generate_answer(agent_settings, agent_documents):
    first, _ = agent_documents
    with patch("services.agent_service.request_tool_turn", side_effect=LLMError("Falha de conexão")), patch(
        "services.chat_service.request_structured"
    ) as generation:
        with pytest.raises(LLMError, match="conexão"):
            ask_question(agent_settings, "Pergunta", [first.id])
        generation.assert_not_called()


def test_sdk_tool_results_are_sent_back_with_matching_call_id(agent_settings, agent_documents):
    from copy import deepcopy
    from types import SimpleNamespace
    first, _ = agent_documents
    agent_settings.openai_api_key = SecretStr("fake")
    arguments = {"document_id": first.id, "page_number": 2, "offset": 0}
    sdk_item = Mock()
    sdk_item.model_dump.return_value = tool("read_page", arguments)[0]
    snapshots = []

    def respond(**kwargs):
        snapshots.append(deepcopy(kwargs["input"]))
        return SimpleNamespace(status="completed", output=[sdk_item] if len(snapshots) == 1 else [])

    with patch("services.llm_service.OpenAI") as client, patch(
        "services.chat_service.request_structured", return_value=output_for(first)
    ):
        client.return_value.__enter__.return_value.responses.create.side_effect = respond
        response = ask_question(agent_settings, "Há exceções?", [first.id])
    assert response.evidence and len(snapshots) == 2
    assert len(snapshots[0]) == 1
    feedback = snapshots[1][-1]
    assert feedback["type"] == "function_call_output" and feedback["call_id"] == "call_1"
    excerpts = json.loads(feedback["output"])["excerpts"]
    assert excerpts[0]["text"].strip() == "Excecao: aviso previo de 5 dias."


def test_agent_chat_page_does_not_repeat_work_on_rerun(agent_settings, agent_documents, embeddings):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR
    first, _ = agent_documents
    decisions = [tool("search_documents", {"query": "multa", "document_ids": [first.id]}),
                 tool("read_page", {"document_id": first.id, "page_number": 2, "offset": 0}, "call_2"), []]
    with patch("config.get_settings", return_value=agent_settings), patch(
        "services.agent_service.request_tool_turn", side_effect=decisions + decisions
    ) as planner, patch("services.chat_service.request_structured", return_value=output_for(first)) as generation:
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/assistant.py").run()
        app.multiselect[0].set_value([first.id]).run()
        planner.assert_not_called()
        app.chat_input[0].set_value("Qual a multa e suas exceções?").run()
        assert not app.exception and not app.error
        assert planner.call_count == 3 and generation.call_count == 1
        assert len([item for item in app.expander if "Fontes verificadas" in item.label]) == 1
        app.run()
        assert planner.call_count == 3 and generation.call_count == 1
        app.chat_input[0].set_value("Qual é a condição de exceção?").run()
        assert not app.exception and not app.error
        assert planner.call_count == 6 and generation.call_count == 2


def test_agent_page_failure_is_stored_and_not_retried(agent_settings, agent_documents):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR
    first, _ = agent_documents
    with patch("config.get_settings", return_value=agent_settings), patch(
        "services.agent_service.request_tool_turn", side_effect=LLMError("Não foi possível conectar à OpenAI.")
    ) as planner:
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/assistant.py").run()
        app.multiselect[0].set_value([first.id]).run()
        app.chat_input[0].set_value("Pergunta").run()
        assert not app.exception and len(app.error) == 1
        app.run()
        assert planner.call_count == 1
