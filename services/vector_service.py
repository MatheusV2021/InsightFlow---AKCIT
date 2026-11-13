"""Índice Qdrant local reconstruível; SQLite permanece a origem das fontes."""

import hashlib
import json
from contextlib import closing
from threading import RLock
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from config import (CHAT_CHUNK_CHARS, CHAT_CHUNK_OVERLAP, MAX_CHAT_CHUNKS,
                    MAX_CHAT_CONTEXT_CHARS, Settings)
from database import repository
from models.schemas import SourcePage
from services.llm_service import LLMError, embed_texts

# Serializa sessões Streamlit no mesmo processo. Outros processos não podem abrir
# a mesma pasta local; o bloqueio de arquivo do Qdrant é respeitado.
_lock = RLock()


def collection_name(settings: Settings) -> str:
    identity = json.dumps([str(settings.database_path.resolve()), settings.ai_provider, settings.active_embedding_model,
                           settings.active_embedding_dimensions, CHAT_CHUNK_CHARS, CHAT_CHUNK_OVERLAP, 1])
    return "documents_" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def document_filter(document_ids: list[str]) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(
        key="document_id", match=models.MatchAny(any=document_ids),
    )])


def build_chunks(pages: list[SourcePage]) -> dict[str, SourcePage]:
    chunks = {}
    for page in pages:
        for start in range(0, len(page.text), CHAT_CHUNK_CHARS - CHAT_CHUNK_OVERLAP):
            text = page.text[start:start + CHAT_CHUNK_CHARS]
            if text.strip():
                source = page.model_copy(update={"text": text})
                identity = json.dumps([source.model_dump(), start], sort_keys=True, ensure_ascii=False)
                chunks[str(uuid5(NAMESPACE_URL, identity))] = source
            if start + CHAT_CHUNK_CHARS >= len(page.text):
                break
    return chunks


def _stored_ids(client: QdrantClient, name: str, selection: models.Filter) -> set[str]:
    ids = set()
    offset = None
    while True:
        records, offset = client.scroll(name, scroll_filter=selection, offset=offset,
                                        limit=256, with_payload=False, with_vectors=False)
        ids.update(str(record.id) for record in records)
        if offset is None:
            return ids


def retrieve_vector_chunks(settings: Settings, question: str, document_ids: list[str]) -> tuple[list[SourcePage], list[str]]:
    """Sincroniza a seleção sob demanda e recupera fontes atuais, nunca texto do payload."""
    if settings.demo_mode:
        raise LLMError("O índice vetorial está desativado no modo demonstração.")
    pages = repository.get_selected_document_pages(settings.database_path, document_ids)
    chunks = build_chunks(pages)
    selection = document_filter(document_ids)
    name = collection_name(settings)
    try:
        with _lock:
            settings.qdrant_path.mkdir(parents=True, exist_ok=True)
            with closing(QdrantClient(path=str(settings.qdrant_path))) as client:
                if not client.collection_exists(name):
                    client.create_collection(name, vectors_config=models.VectorParams(
                        size=settings.active_embedding_dimensions, distance=models.Distance.COSINE,
                    ))
                existing = _stored_ids(client, name, selection)
                missing = sorted(set(chunks) - existing)
                # IDs incluem texto e referências: alterações nunca reutilizam vetores antigos.
                # Só remove a versão anterior depois de concluir todos os lotes novos.
                for start in range(0, len(missing), 16):
                    batch = missing[start:start + 16]
                    vectors = embed_texts(settings, [chunks[key].text for key in batch])
                    client.upsert(name, points=[models.PointStruct(
                        id=key, vector=vector, payload=chunks[key].model_dump(),
                    ) for key, vector in zip(batch, vectors, strict=True)], wait=True)
                stale = sorted(existing - set(chunks))
                if stale:
                    client.delete(name, points_selector=models.PointIdsList(points=stale), wait=True)
                # Remove vetores de documentos excluídos do SQLite, inclusive fora da seleção.
                live_ids = [document.id for document in repository.list_documents(settings.database_path)]
                client.delete(name, points_selector=models.FilterSelector(filter=models.Filter(
                    must_not=[models.FieldCondition(key="document_id", match=models.MatchAny(any=live_ids))],
                )), wait=True)
                if not chunks:
                    return [], []
                query = embed_texts(settings, [question.strip()])[0]
                hits = client.query_points(
                    name, query=query, query_filter=selection, limit=MAX_CHAT_CHUNKS + 1,
                    score_threshold=settings.vector_score_threshold, with_payload=False,
                ).points
    except LLMError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise LLMError("Não foi possível acessar o índice vetorial local. Confira o armazenamento e se outra instância do aplicativo está usando a mesma pasta Qdrant.") from None
    # Retorna exclusivamente recortes reconstruídos a partir do SQLite atual.
    sources = []
    remaining = MAX_CHAT_CONTEXT_CHARS
    warnings = []
    for hit in hits:
        source = chunks.get(str(hit.id))
        if source is None:
            continue
        if len(sources) >= MAX_CHAT_CHUNKS or remaining <= 0:
            warnings = ["Parte dos trechos correspondentes não foi enviada por causa dos limites de contexto."]
            break
        text = source.text[:remaining]
        if len(text) < len(source.text):
            warnings = ["Parte dos trechos correspondentes não foi enviada por causa dos limites de contexto."]
        sources.append(source.model_copy(update={"text": text}))
        remaining -= len(text)
    return sources, warnings
