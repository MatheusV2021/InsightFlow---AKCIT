"""SDK Google real para schemas, clientes simulados e nenhuma chamada externa."""

from contextlib import closing
import json
from unittest.mock import patch

from google.genai import errors, types
from httpx2 import ConnectError
import pytest
from pydantic import SecretStr
from qdrant_client import QdrantClient

from config import Settings
from database.db import get_connection
from models.schemas import AnalystOutput, ChatModelOutput, ChatStatement, Evidence
from services.agent_service import agent_tools
from services.analysis_service import analyze_documents
from services.chat_service import ask_question, INSUFFICIENT_EVIDENCE, revalidate_response_sources
from services.document_service import process_document
from services.llm_service import LLMError, embed_texts, request_structured, request_tool_turn
from services.vector_service import collection_name


def response(parts, finish="STOP"):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        finish_reason=finish, content=types.Content(role="model", parts=parts),
    )])


def text_response(text):
    return response([types.Part(text=text)])


def function_response(name, args, call_id="call_1", signature=b"signature"):
    return response([types.Part(function_call=types.FunctionCall(id=call_id, name=name, args=args),
                                thought_signature=signature)])


@pytest.fixture
def gemini_settings(document_settings):
    return document_settings.model_copy(update={
        "ai_provider": "gemini", "gemini_api_key": SecretStr("fake-google-key"),
        "gemini_embedding_dimensions": 3, "chat_retrieval": "qdrant", "chat_agent_enabled": True,
    })


def test_structured_response_uses_google_and_closes_client(gemini_settings):
    with patch("services.gemini_service.genai.Client") as client:
        generate = client.return_value.models.generate_content
        generate.return_value = text_response('{"facts": []}')
        result = request_structured(gemini_settings, "instructions", "payload", AnalystOutput)
        assert result == AnalystOutput(facts=[])
        kwargs = client.call_args.kwargs
        assert kwargs["api_key"] == "fake-google-key" and kwargs["vertexai"] is False
        assert kwargs["http_options"].timeout == 60000
        assert kwargs["http_options"].retry_options.attempts == 1
        assert generate.call_args.kwargs["model"] == gemini_settings.gemini_model
        config = generate.call_args.kwargs["config"]
        assert config.response_mime_type == "application/json" and config.response_schema is AnalystOutput
        assert config.automatic_function_calling.disable is True
        assert config.max_output_tokens == 4000
        client.return_value.close.assert_called_once()


@pytest.mark.parametrize("reply", [
    types.GenerateContentResponse(), text_response("not json"),
    text_response('{"facts":"invalid"}'), response([types.Part(text="{}")], finish="MAX_TOKENS"),
    response([types.Part(text="{}")], finish="SAFETY"),
])
def test_invalid_or_blocked_responses_are_not_used(gemini_settings, reply):
    with patch("services.gemini_service.genai.Client") as client:
        client.return_value.models.generate_content.return_value = reply
        with pytest.raises(LLMError):
            request_structured(gemini_settings, "instructions", "payload", AnalystOutput)
        client.return_value.close.assert_called_once()


@pytest.mark.parametrize("operation", ["structured", "embedding", "tool"])
@pytest.mark.parametrize("demo", [True, False])
def test_demo_and_missing_key_never_create_google_client(gemini_settings, operation, demo):
    from pydantic import SecretStr
    settings = gemini_settings.model_copy(update={"demo_mode": demo, "gemini_api_key": SecretStr("")})
    with patch("services.gemini_service.genai.Client") as client:
        with pytest.raises(LLMError, match="demonstração" if demo else "GEMINI_API_KEY"):
            if operation == "structured":
                request_structured(settings, "instructions", "payload", AnalystOutput)
            elif operation == "embedding":
                embed_texts(settings, ["texto"])
            else:
                request_tool_turn(settings, "instructions", [], agent_tools())
        client.assert_not_called()


@pytest.mark.parametrize("code,match", [(400, "model"), (401, "chave"), (403, "acesso"),
                                        (404, "model"), (429, "cota"), (503, "concluiu")])
def test_google_errors_are_sanitized(gemini_settings, code, match):
    with patch("services.gemini_service.genai.Client") as client:
        client.return_value.models.generate_content.side_effect = errors.APIError(code, {"error": {"message": "private-detail"}})
        with pytest.raises(LLMError, match=match) as caught:
            request_structured(gemini_settings, "instructions", "payload", AnalystOutput)
        assert "private-detail" not in str(caught.value)


def test_network_error_is_sanitized(gemini_settings):
    with patch("services.gemini_service.genai.Client") as client:
        client.return_value.models.generate_content.side_effect = ConnectError("private-detail")
        with pytest.raises(LLMError, match="conectar"):
            request_structured(gemini_settings, "instructions", "payload", AnalystOutput)


def test_google_embeddings_use_google_model_and_dimensions(gemini_settings):
    with patch("services.gemini_service.genai.Client") as client:
        embed = client.return_value.models.embed_content
        embed.return_value = types.EmbedContentResponse(embeddings=[
            types.ContentEmbedding(values=[1., 0., 0.]), types.ContentEmbedding(values=[0., 1., 0.]),
        ])
        assert embed_texts(gemini_settings, ["primeiro", "segundo"]) == [[1., 0., 0.], [0., 1., 0.]]
        assert embed.call_args.kwargs["model"] == "gemini-embedding-001"
        assert embed.call_args.kwargs["contents"] == ["primeiro", "segundo"]
        assert embed.call_args.kwargs["config"].output_dimensionality == 3


@pytest.mark.parametrize("vectors", [[], [[1.]], [[0., 0., 0.]], [[float("nan"), 0., 0.]],
                                      [[1., 0., 0.], [0., 1., 0.]]])
def test_wrong_google_embedding_count_dimensions_or_values_are_rejected(gemini_settings, vectors):
    with patch("services.gemini_service.genai.Client") as client:
        client.return_value.models.embed_content.return_value = types.EmbedContentResponse(
            embeddings=[types.ContentEmbedding(values=vector) for vector in vectors])
        with pytest.raises(LLMError, match="embeddings inválidos"):
            embed_texts(gemini_settings, ["texto"])


def test_tools_preserve_native_content_signatures_and_function_ids(gemini_settings):
    messages = [{"role": "user", "content": "Pergunta"}]
    with patch("services.gemini_service.genai.Client") as client:
        generate = client.return_value.models.generate_content
        generate.side_effect = [function_response("read_page", {"document_id": "doc", "page_number": 1, "offset": 0}),
                                text_response("Pronto")]
        output = request_tool_turn(gemini_settings, "instructions", messages, agent_tools())
        assert output[0]["name"] == "read_page" and output[0]["call_id"] == "call_1"
        messages.extend(output)
        messages.append({"type": "function_call_output", "call_id": "call_1", "output": '{"excerpts": []}'})
        assert request_tool_turn(gemini_settings, "instructions", messages, agent_tools()) == []
        contents = generate.call_args.kwargs["contents"]
        assert contents[1].parts[0].thought_signature == b"signature"
        assert contents[2].parts[0].function_response.name == "read_page"
        assert contents[2].parts[0].function_response.id == "call_1"
        assert contents[2].parts[0].function_response.response == {"excerpts": []}
        config = generate.call_args.kwargs["config"]
        assert config.automatic_function_calling.disable is True and config.max_output_tokens == 1000
        assert {fn.name for fn in config.tools[0].function_declarations} == {"search_documents", "read_page"}


def test_parallel_calls_fail_before_execution(gemini_settings):
    reply = response([types.Part(function_call=types.FunctionCall(name="read_page", args={})),
                      types.Part(function_call=types.FunctionCall(name="search_documents", args={}))])
    with patch("services.gemini_service.genai.Client") as client:
        client.return_value.models.generate_content.return_value = reply
        with pytest.raises(LLMError, match="simultâneas"):
            request_tool_turn(gemini_settings, "instructions", [], agent_tools())


def test_provider_and_dimensions_isolate_vector_collections(gemini_settings):
    name = collection_name(gemini_settings)
    assert name != collection_name(gemini_settings.model_copy(update={"ai_provider": "openai"}))
    assert name != collection_name(gemini_settings.model_copy(update={"gemini_embedding_dimensions": 768}))


@pytest.mark.parametrize("operation", ["structured", "tool", "embedding"])
def test_limits_stop_gemini_calls_before_network(gemini_settings, operation):
    from config import MAX_LLM_INPUT_CHARS
    with patch("services.gemini_service.genai.Client") as client:
        with pytest.raises(LLMError):
            if operation == "structured":
                request_structured(gemini_settings, "instructions", "x" * (MAX_LLM_INPUT_CHARS + 1), AnalystOutput)
            elif operation == "tool":
                request_tool_turn(gemini_settings, "instructions", [{"role": "user", "content": "x" * MAX_LLM_INPUT_CHARS}], agent_tools())
            else:
                embed_texts(gemini_settings, ["x" * 1801])
        client.assert_not_called()


def test_gemini_chat_still_rejects_invented_sources(gemini_settings, make_pdf):
    doc = process_document(gemini_settings, "doc.pdf", make_pdf(("Multa de 10 reais.",)))
    output = ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(
        text="Multa de 100 reais.", evidence=[Evidence(document_id=doc.id, filename=doc.original_filename,
                                                      page_number=1, quote="Multa de 100 reais.")])])
    with patch("services.gemini_service.genai.Client") as client:
        client.return_value.models.generate_content.side_effect = [
            function_response("read_page", {"document_id": doc.id, "page_number": 1, "offset": 0}),
            text_response("Pronto"), text_response(output.model_dump_json()),
        ]
        result = ask_question(gemini_settings, "Qual a multa?", [doc.id])
    assert result.answer == INSUFFICIENT_EVIDENCE and not result.evidence


def test_gemini_page_displays_provider_and_does_not_repeat_calls(gemini_settings, make_pdf):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR
    doc = process_document(gemini_settings, "doc.pdf", make_pdf(("Multa de 10 reais.",)))
    output = ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(
        text="Multa de 10 reais.", evidence=[Evidence(document_id=doc.id, filename=doc.original_filename,
                                                     page_number=1, quote="Multa de 10 reais.")])])
    with patch("config.get_settings", return_value=gemini_settings), patch("services.gemini_service.genai.Client") as client:
        generate = client.return_value.models.generate_content
        generate.side_effect = [function_response("read_page", {"document_id": doc.id, "page_number": 1, "offset": 0}),
                                text_response("Pronto"), text_response(output.model_dump_json())]
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/assistant.py").run()
        app.multiselect[0].set_value([doc.id]).run()
        generate.assert_not_called()
        app.chat_input[0].set_value("Qual a multa?").run()
        assert not app.exception and not app.error
        assert any("Gemini" in caption.value for caption in app.caption)
        assert generate.call_count == 3
        app.run()
        assert generate.call_count == 3


def test_full_gemini_chat_uses_qdrant_sqlite_and_validated_sources(gemini_settings, make_pdf):
    doc = process_document(gemini_settings, "contrato.pdf", make_pdf(("Multa de 10 reais.", "Excecao: aviso previo de 5 dias.")))
    model_output = ChatModelOutput(sufficient_evidence=True, statements=[ChatStatement(
        text="É preciso aviso prévio.", evidence=[Evidence(document_id=doc.id, filename=doc.original_filename,
                                                         page_number=2, quote="Excecao: aviso previo de 5 dias.")])])
    replies = [function_response("search_documents", {"query": "penalidade", "document_ids": [doc.id]}),
               function_response("read_page", {"document_id": doc.id, "page_number": 2, "offset": 0}, "call_2"),
               text_response("Pronto"), text_response(model_output.model_dump_json())]
    with patch("services.gemini_service.genai.Client") as client:
        client.return_value.models.generate_content.side_effect = replies
        client.return_value.models.embed_content.side_effect = lambda **kwargs: types.EmbedContentResponse(
            embeddings=[types.ContentEmbedding(values=[1., 0., 0.]) for _ in kwargs["contents"]])
        result = ask_question(gemini_settings, "Qual a penalidade e a exceção?", [doc.id])
        assert result.evidence and "[1]" in result.answer
        assert client.return_value.models.generate_content.call_count == 4
        assert client.return_value.models.embed_content.call_count == 2
    with closing(QdrantClient(path=str(gemini_settings.qdrant_path))) as client:
        assert client.count(collection_name(gemini_settings)).count == 2
    with get_connection(gemini_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = 'Alterado'")
    assert revalidate_response_sources(gemini_settings, result).answer == INSUFFICIENT_EVIDENCE


def test_analysis_cache_separates_providers_with_same_model_name(gemini_settings, make_pdf):
    doc = process_document(gemini_settings, "doc.pdf", make_pdf(("Contrato com obrigacoes e prazos de pagamento.",)))
    gemini_settings.gemini_model = "same-model"
    other = gemini_settings.model_copy(update={"ai_provider": "openai", "openai_model": "same-model"})
    with patch("services.analysis_service.request_structured", return_value=AnalystOutput(facts=[])) as model:
        first = analyze_documents(gemini_settings, [doc.id])
        second = analyze_documents(other, [doc.id])
        assert model.call_count == 2 and first.id != second.id
        assert analyze_documents(gemini_settings, [doc.id]).id == first.id
        assert model.call_count == 2
