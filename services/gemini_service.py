"""SDK Google Gen AI: geração, ferramentas manuais e embeddings, sem estado remoto."""

from contextlib import closing, contextmanager
import json
import math
from typing import TypeVar
from uuid import uuid4

from google import genai
from google.genai import errors, types
from httpx2 import HTTPError
from pydantic import BaseModel

from config import MAX_LLM_INPUT_CHARS, MAX_LLM_OUTPUT_TOKENS, Settings
from services.llm_service import LLMError

ResponseSchema = TypeVar("ResponseSchema", bound=BaseModel)


@contextmanager
def _client(settings: Settings):
    if settings.demo_mode:
        raise LLMError("A API está desativada no modo demonstração. Use DEMO_MODE=false.")
    if not settings.gemini_api_key.get_secret_value().strip():
        raise LLMError("Configure GEMINI_API_KEY no .env para consultar o Gemini.")
    try:
        with closing(genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(), vertexai=False,
            http_options=types.HttpOptions(timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)),
        )) as client:
            yield client
    except errors.APIError as error:
        if error.code in {401, 403}:
            message = "A chave Gemini não foi aceita ou não tem acesso ao modelo. Confira GEMINI_API_KEY."
        elif error.code == 429:
            message = "Limite de requisições ou cota do Gemini atingido. Confira sua cota e tente novamente."
        elif error.code == 404:
            message = "O modelo Gemini configurado não está disponível para esta conta. Confira GEMINI_MODEL ou GEMINI_EMBEDDING_MODEL."
        elif error.code == 400:
            message = "O Gemini não aceitou a consulta. Confira a chave, GEMINI_MODEL, o modelo de embeddings e suas dimensões."
        else:
            message = "O Gemini não concluiu a consulta: serviço indisponível ou sob alta demanda. Tente novamente mais tarde."
        raise LLMError(message) from None
    except (HTTPError, TimeoutError, ConnectionError):
        raise LLMError("Não foi possível conectar ao Gemini. Confira a conexão e tente novamente.") from None
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        raise LLMError("O Gemini retornou uma estrutura inválida. A consulta não foi utilizada.") from None


def _candidate(response: types.GenerateContentResponse) -> types.Candidate:
    if not response.candidates or len(response.candidates) != 1:
        raise LLMError("O Gemini não retornou uma resposta utilizável ou recusou a solicitação.")
    candidate = response.candidates[0]
    if candidate.finish_reason != types.FinishReason.STOP or not candidate.content or not candidate.content.parts:
        raise LLMError("O Gemini retornou uma resposta incompleta ou bloqueada. A resposta não foi utilizada.")
    return candidate


def _generation_config(settings: Settings, instructions: str, **kwargs) -> types.GenerateContentConfig:
    config = dict(system_instruction=instructions, max_output_tokens=MAX_LLM_OUTPUT_TOKENS,
                  automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    # Mantém espaço para a saída nos modelos com raciocínio obrigatório.
    if settings.gemini_model.startswith(("gemini-3", "gemini-4")):
        config["thinking_config"] = types.ThinkingConfig(thinking_level="LOW")
    elif settings.gemini_model.startswith("gemini-2.5-flash"):
        config["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    config.update(kwargs)
    return types.GenerateContentConfig(**config)


def request_structured(settings: Settings, instructions: str, payload: str, schema: type[ResponseSchema]) -> ResponseSchema:
    if len(payload) > MAX_LLM_INPUT_CHARS:
        raise LLMError("O conteúdo estruturado excedeu o limite da consulta. Selecione menos documentos.")
    with _client(settings) as client:
        response = client.models.generate_content(
            model=settings.gemini_model, contents=payload,
            config=_generation_config(settings, instructions, response_mime_type="application/json", response_schema=schema),
        )
        candidate = _candidate(response)
        # Ignora partes internas de raciocínio; a saída continua sujeita ao schema e às fontes.
        text = "".join(part.text for part in candidate.content.parts if part.text and not part.thought)
        return schema.model_validate_json(text)


def embed_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    if not texts or len(texts) > 16 or any(not text.strip() or len(text) > 1800 for text in texts):
        raise LLMError("Lote de embeddings inválido ou acima do limite.")
    with _client(settings) as client:
        # embedding-001 mantém um vetor por string. Modelos multimodais podem agregar
        # entradas; a checagem de cardinalidade abaixo impede indexação incorreta.
        response = client.models.embed_content(
            model=settings.gemini_embedding_model, contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=settings.gemini_embedding_dimensions),
        )
        vectors = [item.values for item in response.embeddings or []]
        if len(vectors) != len(texts) or any(
            vector is None or len(vector) != settings.gemini_embedding_dimensions or
            not all(math.isfinite(value) for value in vector) or not any(vector)
            for vector in vectors
        ):
            raise LLMError("O Gemini retornou embeddings inválidos. Confira o modelo e as dimensões configuradas.")
        return vectors


def _contents(messages: list[dict]) -> list[types.Content]:
    contents = []
    calls = {}
    for item in messages:
        if item.get("role") == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=item["content"])]))
        elif item.get("type") == "function_call":
            # Reenvia a parte original, incluindo thought_signature quando existir.
            original = types.Content.model_validate(item["gemini_content"])
            contents.append(original)
            function_call = next(part.function_call for part in original.parts if part.function_call)
            calls[item["call_id"]] = function_call
        elif item.get("type") == "function_call_output":
            call = calls[item["call_id"]]
            contents.append(types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                name=call.name, id=call.id, response=json.loads(item["output"]),
            ))]))
        else:
            raise ValueError("Item de investigação inválido")
    return contents


def request_tool_turn(settings: Settings, instructions: str, messages: list[dict], tools: list[dict]) -> list[dict]:
    if len(json.dumps(messages, ensure_ascii=False)) > MAX_LLM_INPUT_CHARS:
        raise LLMError("O contexto do agente excedeu o limite da consulta. Selecione menos documentos.")
    with _client(settings) as client:
        declarations = [types.FunctionDeclaration(name=tool["name"], description=tool["description"],
                                                  parameters_json_schema=tool["parameters"]) for tool in tools]
        response = client.models.generate_content(
            model=settings.gemini_model, contents=_contents(messages),
            config=_generation_config(settings, instructions, max_output_tokens=1000,
                                      tools=[types.Tool(function_declarations=declarations)]),
        )
        candidate = _candidate(response)
        calls = [part.function_call for part in candidate.content.parts if part.function_call]
        if not calls:
            return []  # O texto livre do planejador nunca é usado como resposta.
        if len(calls) != 1:
            raise LLMError("O Gemini solicitou ferramentas simultâneas. A consulta foi interrompida.")
        call = calls[0]
        return [{"type": "function_call", "call_id": call.id or str(uuid4()), "name": call.name,
                 "arguments": json.dumps(call.args or {}, ensure_ascii=False),
                 "gemini_content": candidate.content.model_dump(mode="json", exclude_none=True)}]
