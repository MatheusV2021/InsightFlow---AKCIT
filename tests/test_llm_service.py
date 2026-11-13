"""Contrato do SDK com cliente simulado; nenhuma chamada externa."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from openai import APIConnectionError, AuthenticationError, BadRequestError, RateLimitError

from config import MAX_LLM_INPUT_CHARS, MAX_LLM_OUTPUT_TOKENS, Settings
from models.schemas import AnalystOutput
from services.llm_service import LLMError, request_structured, embed_texts, request_tool_turn


def test_missing_key_is_clear_and_does_not_instantiate_client():
    with patch("services.llm_service.OpenAI") as client:
        with pytest.raises(LLMError, match="OPENAI_API_KEY"):
            request_structured(Settings(), "instructions", "input", AnalystOutput)
        client.assert_not_called()


def test_installed_sdk_contract_and_pydantic_result():
    settings = Settings(openai_api_key="fake-key-for-tests", openai_model="configured-model")
    with patch("services.llm_service.OpenAI") as client:
        parse = client.return_value.__enter__.return_value.responses.parse
        parse.return_value = SimpleNamespace(status="completed", output_parsed=AnalystOutput(facts=[]))
        result = request_structured(settings, "instructions", "input", AnalystOutput)
        assert result == AnalystOutput(facts=[])
        client.assert_called_once_with(api_key="fake-key-for-tests", timeout=60.0, max_retries=0)
        parse.assert_called_once_with(
            model="configured-model", instructions="instructions", input="input", text_format=AnalystOutput,
            max_output_tokens=MAX_LLM_OUTPUT_TOKENS, store=False,
        )
        client.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize(("error", "message"), [
    (APIConnectionError(request=Mock()), "conectar"),
    (RateLimitError("private-detail", response=Mock(status_code=429), body=None), "cota"),
    (AuthenticationError("private-detail", response=Mock(status_code=401), body=None), "chave"),
    (BadRequestError("private-detail", response=Mock(status_code=400), body=None), "modelo"),
    (ValueError("private-detail"), "estrutura"),
])
def test_api_errors_are_sanitized(error, message):
    with patch("services.llm_service.OpenAI") as client:
        client.return_value.__enter__.return_value.responses.parse.side_effect = error
        with pytest.raises(LLMError, match=message) as caught:
            request_structured(Settings(openai_api_key="fake"), "instructions", "input", AnalystOutput)
    assert "private-detail" not in str(caught.value)


@pytest.mark.parametrize("response", [
    SimpleNamespace(status="incomplete", output_parsed=None),
    SimpleNamespace(status="completed", output_parsed=None),
    SimpleNamespace(status="completed", output_parsed=SimpleNamespace(model_dump=lambda: {"facts": "invalid"})),
])
def test_invalid_or_refused_responses(response):
    with patch("services.llm_service.OpenAI") as client:
        client.return_value.__enter__.return_value.responses.parse.return_value = response
        with pytest.raises(LLMError):
            request_structured(Settings(openai_api_key="fake"), "instructions", "input", AnalystOutput)


def test_payload_limit_is_enforced_before_network():
    with patch("services.llm_service.OpenAI") as client:
        with pytest.raises(LLMError, match="limite"):
            request_structured(Settings(openai_api_key="fake"), "instructions", "a" * (MAX_LLM_INPUT_CHARS + 1), AnalystOutput)
        client.assert_not_called()


def test_embedding_sdk_contract_restores_input_order():
    settings = Settings(openai_api_key="fake", embedding_dimensions=2)
    with patch("services.llm_service.OpenAI") as client:
        create = client.return_value.__enter__.return_value.embeddings.create
        create.return_value = SimpleNamespace(data=[
            SimpleNamespace(index=1, embedding=[0.0, 1.0]),
            SimpleNamespace(index=0, embedding=[1.0, 0.0]),
        ])
        assert embed_texts(settings, ["primeiro", "segundo"]) == [[1.0, 0.0], [0.0, 1.0]]
        create.assert_called_once_with(model="text-embedding-3-small", input=["primeiro", "segundo"],
                                       dimensions=2, encoding_format="float")
        client.assert_called_once_with(api_key="fake", timeout=60.0, max_retries=0)


@pytest.mark.parametrize("data", [[], [SimpleNamespace(index=1, embedding=[1.0, 0.0])],
    [SimpleNamespace(index=0, embedding=[1.0])],
    [SimpleNamespace(index=0, embedding=[float("nan"), 1.0])],
    [SimpleNamespace(index=0, embedding=[0.0, 0.0])],
])
def test_invalid_embeddings_are_rejected(data):
    with patch("services.llm_service.OpenAI") as client:
        client.return_value.__enter__.return_value.embeddings.create.return_value = SimpleNamespace(data=data)
        with pytest.raises(LLMError, match="inválidos"):
            embed_texts(Settings(openai_api_key="fake", embedding_dimensions=2), ["texto"])


@pytest.mark.parametrize("settings", [Settings(demo_mode=True, openai_api_key="fake"), Settings()])
def test_embeddings_require_key_and_block_demo(settings):
    with patch("services.llm_service.OpenAI") as client:
        with pytest.raises(LLMError):
            embed_texts(settings, ["texto"])
        client.assert_not_called()


def test_embedding_network_error_is_sanitized():
    with patch("services.llm_service.OpenAI") as client:
        client.return_value.__enter__.return_value.embeddings.create.side_effect = APIConnectionError(request=Mock())
        with pytest.raises(LLMError, match="conectar"):
            embed_texts(Settings(openai_api_key="fake"), ["texto"])


def test_tool_turn_sdk_contract_and_function_call_output():
    from services.agent_service import agent_tools
    call = {"type": "function_call", "call_id": "call_1", "name": "read_page",
            "arguments": '{"document_id":"doc","page_number":1,"offset":0}'}
    item = Mock()
    item.model_dump.return_value = call
    messages = [{"role": "user", "content": "pergunta"}]
    tools = agent_tools()
    with patch("services.llm_service.OpenAI") as client:
        create = client.return_value.__enter__.return_value.responses.create
        create.return_value = SimpleNamespace(status="completed", output=[item])
        assert request_tool_turn(Settings(openai_api_key="fake"), "instruções", messages, tools) == [call]
        create.assert_called_once_with(model="gpt-4.1-mini", instructions="instruções", input=messages,
                                        tools=tools, tool_choice="auto", parallel_tool_calls=False,
                                        max_output_tokens=1000, store=False)
        client.assert_called_once_with(api_key="fake", timeout=60.0, max_retries=0)
    for definition in tools:
        schema = definition["parameters"]
        assert definition["strict"] is True and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize("status,output", [
    ("incomplete", []),
    ("completed", [{"type": "function_call"}, {"type": "function_call"}]),
    ("completed", [{"type": "web_search_call"}]),
    ("completed", [{"type": "message", "content": [{"type": "refusal"}]}]),
])
def test_tool_turn_fails_closed_on_refusal_or_invalid_output(status, output):
    items = []
    for value in output:
        item = Mock()
        item.model_dump.return_value = value
        items.append(item)
    with patch("services.llm_service.OpenAI") as client:
        client.return_value.__enter__.return_value.responses.create.return_value = SimpleNamespace(status=status, output=items)
        with pytest.raises(LLMError):
            request_tool_turn(Settings(openai_api_key="fake"), "instruções", [], [])


@pytest.mark.parametrize("settings,messages", [
    (Settings(demo_mode=True, openai_api_key="fake"), []), (Settings(), []),
    (Settings(openai_api_key="fake"), [{"role": "user", "content": "x" * MAX_LLM_INPUT_CHARS}]),
])
def test_tool_turn_checks_demo_key_and_payload_before_network(settings, messages):
    with patch("services.llm_service.OpenAI") as client:
        with pytest.raises(LLMError):
            request_tool_turn(settings, "instruções", messages, [])
        client.assert_not_called()


@pytest.mark.parametrize(("error", "message"), [
    (APIConnectionError(request=Mock()), "conectar"),
    (RateLimitError("private-detail", response=Mock(status_code=429), body=None), "cota"),
    (AuthenticationError("private-detail", response=Mock(status_code=401), body=None), "chave"),
    (BadRequestError("private-detail", response=Mock(status_code=400), body=None), "modelo"),
])
def test_tool_turn_sanitizes_api_failures(error, message):
    with patch("services.llm_service.OpenAI") as client:
        client.return_value.__enter__.return_value.responses.create.side_effect = error
        with pytest.raises(LLMError, match=message) as caught:
            request_tool_turn(Settings(openai_api_key="fake"), "instruções", [], [])
    assert "private-detail" not in str(caught.value)
