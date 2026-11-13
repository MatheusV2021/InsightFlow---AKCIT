"""Integração sequencial com saídas estruturadas da API Responses."""

from typing import TypeVar

from openai import APIConnectionError, AuthenticationError, OpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, ValidationError

from config import MAX_LLM_INPUT_CHARS, MAX_LLM_OUTPUT_TOKENS, Settings

ResponseSchema = TypeVar("ResponseSchema", bound=BaseModel)


class LLMError(RuntimeError):
    """Erro sanitizado que pode ser apresentado na interface."""


def request_structured(
    settings: Settings, instructions: str, payload: str, schema: type[ResponseSchema]
) -> ResponseSchema:
    """Executa uma chamada limitada, sem retentativas automáticas ou logs de conteúdo."""
    if settings.demo_mode:
        raise LLMError("A API está desativada no modo demonstração. Use o fluxo local ou DEMO_MODE=false.")
    if not settings.openai_api_key.get_secret_value().strip():
        raise LLMError("Configure OPENAI_API_KEY no .env para consultar a IA.")
    if len(payload) > MAX_LLM_INPUT_CHARS:
        raise LLMError("O conteúdo estruturado excedeu o limite da consulta. Selecione menos documentos.")
    try:
        with OpenAI(
            api_key=settings.openai_api_key.get_secret_value(), timeout=60.0, max_retries=0
        ) as client:
            response = client.responses.parse(
                model=settings.openai_model,
                instructions=instructions,
                input=payload,
                text_format=schema,
                max_output_tokens=MAX_LLM_OUTPUT_TOKENS,
                store=False,
            )
        if response.status != "completed" or response.output_parsed is None:
            raise LLMError("A IA retornou uma resposta incompleta ou recusou a solicitação. A resposta não foi utilizada.")
        return schema.model_validate(response.output_parsed.model_dump())
    except AuthenticationError:
        raise LLMError("A chave OpenAI não foi aceita. Confira OPENAI_API_KEY no .env.") from None
    except RateLimitError:
        raise LLMError("Limite de requisições ou cota da OpenAI atingido. Aguarde e confira sua cota.") from None
    except APIConnectionError:
        raise LLMError("Não foi possível conectar à OpenAI. Confira a conexão e tente novamente.") from None
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise LLMError("A resposta da IA não corresponde à estrutura esperada. A resposta não foi utilizada.") from None
    except OpenAIError:
        raise LLMError("A OpenAI não concluiu a consulta. Confira o modelo configurado e tente novamente.") from None
