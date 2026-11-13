"""Interface compartilhada para OpenAI e Gemini, sem chamadas no modo demonstração."""

from typing import TypeVar
import math
import json

from openai import APIConnectionError, AuthenticationError, OpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, ValidationError

from config import MAX_LLM_INPUT_CHARS, MAX_LLM_OUTPUT_TOKENS, Settings

ResponseSchema = TypeVar("ResponseSchema", bound=BaseModel)


class LLMError(RuntimeError):
    """Erro sanitizado que pode ser apresentado na interface."""


def request_tool_turn(
    settings: Settings, instructions: str, messages: list[dict], tools: list[dict],
) -> list[dict]:
    """Uma decisão do agente, sem estado remoto e com no máximo uma ferramenta."""
    if settings.demo_mode:
        raise LLMError("O agente está desativado no modo demonstração.")
    if settings.ai_provider == "gemini":
        from services.gemini_service import request_tool_turn as gemini_tool_turn
        return gemini_tool_turn(settings, instructions, messages, tools)
    if not settings.openai_api_key.get_secret_value().strip():
        raise LLMError("Configure OPENAI_API_KEY no .env para consultar a IA.")
    if len(json.dumps(messages, ensure_ascii=False)) > MAX_LLM_INPUT_CHARS:
        raise LLMError("O contexto do agente excedeu o limite da consulta. Selecione menos documentos.")
    try:
        with OpenAI(api_key=settings.openai_api_key.get_secret_value(), timeout=60.0, max_retries=0) as client:
            response = client.responses.create(
                model=settings.openai_model, instructions=instructions, input=messages,
                tools=tools, tool_choice="auto", parallel_tool_calls=False,
                max_output_tokens=1000, store=False,
            )
        if response.status != "completed":
            raise LLMError("O agente retornou uma decisão incompleta. A consulta foi interrompida.")
        output = [item.model_dump(mode="json", exclude_none=True) for item in response.output]
        calls = [item for item in output if item["type"] == "function_call"]
        if len(calls) > 1 or any(item["type"] not in {"function_call", "message", "reasoning"} for item in output):
            raise ValueError("Saída do agente inválida")
        if any(part.get("type") == "refusal" for item in output
               if item["type"] == "message" for part in item.get("content", [])):
            raise LLMError("O agente recusou a solicitação. A consulta foi interrompida.")
        return output
    except AuthenticationError:
        raise LLMError("A chave OpenAI não foi aceita. Confira OPENAI_API_KEY no .env.") from None
    except RateLimitError:
        raise LLMError("Limite de requisições ou cota da OpenAI atingido durante a investigação.") from None
    except APIConnectionError:
        raise LLMError("Não foi possível conectar à OpenAI durante a investigação.") from None
    except OpenAIError:
        raise LLMError("A OpenAI não concluiu a investigação. Confira se o modelo suporta chamadas de ferramentas.") from None
    except (ValueError, TypeError, AttributeError, KeyError):
        raise LLMError("O agente retornou uma decisão inválida. A consulta foi interrompida.") from None


def embed_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    """Gera um lote limitado de vetores, sem retentativas nem logs de conteúdo."""
    if settings.demo_mode:
        raise LLMError("Embeddings estão desativados no modo demonstração.")
    if settings.ai_provider == "gemini":
        from services.gemini_service import embed_texts as gemini_embeddings
        return gemini_embeddings(settings, texts)
    if not settings.openai_api_key.get_secret_value().strip():
        raise LLMError("Configure OPENAI_API_KEY no .env para consultar a IA.")
    if not texts or len(texts) > 16 or any(not text.strip() or len(text) > 1800 for text in texts):
        raise LLMError("Lote de embeddings inválido ou acima do limite.")
    try:
        with OpenAI(api_key=settings.openai_api_key.get_secret_value(), timeout=60.0, max_retries=0) as client:
            response = client.embeddings.create(
                model=settings.embedding_model, input=texts,
                dimensions=settings.embedding_dimensions, encoding_format="float",
            )
        items = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in items] != list(range(len(texts))):
            raise ValueError("Quantidade ou ordem de embeddings inválida")
        vectors = [item.embedding for item in items]
        if any(len(vector) != settings.embedding_dimensions or
               not all(math.isfinite(value) for value in vector) or
               not any(vector) for vector in vectors):
            raise ValueError("Vetor inválido")
        return vectors
    except AuthenticationError:
        raise LLMError("A chave OpenAI não foi aceita. Confira OPENAI_API_KEY no .env.") from None
    except RateLimitError:
        raise LLMError("Limite de requisições ou cota da OpenAI atingido ao gerar embeddings.") from None
    except APIConnectionError:
        raise LLMError("Não foi possível conectar à OpenAI para gerar embeddings.") from None
    except OpenAIError:
        raise LLMError("Não foi possível gerar embeddings. Confira o modelo e suas dimensões.") from None
    except (ValueError, TypeError, AttributeError):
        raise LLMError("A OpenAI retornou embeddings inválidos. A consulta não foi utilizada.") from None


def request_structured(
    settings: Settings, instructions: str, payload: str, schema: type[ResponseSchema]
) -> ResponseSchema:
    """Executa uma chamada limitada, sem retentativas automáticas ou logs de conteúdo."""
    if settings.demo_mode:
        raise LLMError("A API está desativada no modo demonstração. Use o fluxo local ou DEMO_MODE=false.")
    if settings.ai_provider == "gemini":
        from services.gemini_service import request_structured as gemini_structured
        return gemini_structured(settings, instructions, payload, schema)
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
