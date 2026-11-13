"""Contrato do SDK com cliente simulado; nenhuma chamada externa."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from openai import APIConnectionError, AuthenticationError, BadRequestError, RateLimitError

from config import MAX_LLM_INPUT_CHARS, MAX_LLM_OUTPUT_TOKENS, Settings
from models.schemas import AnalystOutput
from services.llm_service import LLMError, request_structured


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
