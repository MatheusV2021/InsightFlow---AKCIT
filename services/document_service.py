"""Validação, processamento e consulta de documentos locais."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config import MAX_DOCUMENTS_PER_OPERATION, MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB, Settings
from database import repository
from database.db import get_connection, initialize_database
from models.schemas import Document, DocumentPage, UploadResult
from services.pdf_service import extract_pdf_text


def initialize_workspace(settings: Settings) -> None:
    """Prepara diretório de arquivos e banco sem acessar serviços externos."""
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    initialize_database(settings.database_path)


def validate_pdf_upload(original_filename: str, content: bytes) -> None:
    """Valida extensão, tamanho e assinatura antes de abrir o arquivo."""
    if Path(original_filename).suffix.lower() != ".pdf":
        raise ValueError("Formato não permitido. Envie apenas arquivos com extensão .pdf.")
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"O arquivo excede o limite de {MAX_FILE_SIZE_MB} MB.")
    if not content:
        raise ValueError("O arquivo está vazio. Envie um PDF válido.")
    if not content.startswith(b"%PDF-"):
        raise ValueError("Assinatura inválida. O arquivo enviado não é um PDF válido.")


def process_document(settings: Settings, original_filename: str, content: bytes) -> Document:
    """Extrai texto, salva o PDF com UUID e persiste páginas atomicamente."""
    validate_pdf_upload(original_filename, content)
    extracted = extract_pdf_text(content)
    has_text = any(page.extracted_text.strip() for page in extracted.pages)
    status = "partial" if len(extracted.pages) < extracted.total_pages else "processed"
    if not has_text:
        status = "no_text"
    document_id = str(uuid4())
    document = Document(
        id=document_id,
        original_filename=Path(original_filename.replace("\\", "/")).name,
        stored_filename=f"{document_id}.pdf",
        uploaded_at=datetime.now(timezone.utc),
        total_pages=extracted.total_pages,
        processed_pages=len(extracted.pages),
        status=status,
    )
    stored_path = settings.uploads_dir / document.stored_filename
    created = False
    try:
        with stored_path.open("xb") as pdf_file:
            created = True
            pdf_file.write(content)
        with get_connection(settings.database_path) as connection:
            repository.insert_document(connection, document)
            repository.insert_pages(connection, document.id, extracted.pages)
    except (OSError, sqlite3.Error, ValueError):
        if created:
            stored_path.unlink(missing_ok=True)
        raise
    return document


def process_documents(settings: Settings, files: list[tuple[str, bytes]]) -> list[UploadResult]:
    """Processa até três arquivos, preservando sucessos quando outro falha."""
    if not 1 <= len(files) <= MAX_DOCUMENTS_PER_OPERATION:
        raise ValueError(f"Selecione de 1 a {MAX_DOCUMENTS_PER_OPERATION} documentos por operação.")
    results = []
    for original_filename, content in files:
        try:
            document = process_document(settings, original_filename, content)
            results.append(UploadResult(original_filename=original_filename, document=document))
        except ValueError as error:
            results.append(UploadResult(original_filename=original_filename, error=str(error)))
        except (OSError, sqlite3.Error):
            results.append(UploadResult(
                original_filename=original_filename,
                error="Não foi possível salvar o documento. Confira o espaço e as permissões do armazenamento local.",
            ))
    return results


def list_documents(settings: Settings) -> list[Document]:
    """Consulta os documentos persistidos, inclusive de sessões anteriores."""
    return repository.list_documents(settings.database_path)


def get_document(settings: Settings, document_id: str) -> Document | None:
    """Consulta metadados pelo ID."""
    return repository.get_document(settings.database_path, document_id)


def get_document_pages(settings: Settings, document_id: str) -> list[DocumentPage]:
    """Consulta o texto persistido por página, sem reprocessar o PDF."""
    return repository.get_document_pages(settings.database_path, document_id)
