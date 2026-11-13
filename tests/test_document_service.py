"""Validações, persistência e recuperação de PDFs locais."""

import sqlite3
from uuid import UUID
from unittest.mock import patch

import pytest

from config import MAX_FILE_SIZE_BYTES, Settings
from database.db import get_connection
from services.document_service import (
    get_document,
    get_document_pages,
    initialize_workspace,
    list_documents,
    process_document,
    process_documents,
    validate_pdf_upload,
)


def test_document_and_pages_survive_reinitialization(document_settings, make_pdf):
    content = make_pdf(("Contract one", "Contract two"))
    document = process_document(document_settings, "../../contract.PDF", content)
    assert str(UUID(document.id)) == document.id
    assert document.original_filename == "contract.PDF"
    assert document.stored_filename == f"{document.id}.pdf"
    assert (document_settings.uploads_dir / document.stored_filename).read_bytes() == content
    assert document.total_pages == document.processed_pages == 2
    assert document.status == "processed"
    assert document.uploaded_at.tzinfo is not None

    restarted_settings = Settings(
        database_path=document_settings.database_path,
        uploads_dir=document_settings.uploads_dir,
    )
    initialize_workspace(restarted_settings)
    assert list_documents(restarted_settings) == [document]
    assert get_document(restarted_settings, document.id) == document
    pages = get_document_pages(restarted_settings, document.id)
    assert [page.page_number for page in pages] == [1, 2]
    assert "Contract one" in pages[0].extracted_text
    assert "Contract two" in pages[1].extracted_text
    assert get_document(restarted_settings, "' OR 1=1 --") is None
    assert get_document_pages(restarted_settings, "missing") == []


@pytest.mark.parametrize(("page_count", "expected_status"), [(1, "no_text"), (12, "no_text")])
def test_empty_text_pdf_is_saved_with_status(document_settings, make_pdf, page_count, expected_status):
    document = process_document(document_settings, "scan.pdf", make_pdf(("",) * page_count))
    assert document.status == expected_status
    assert document.total_pages == page_count
    assert document.processed_pages == min(page_count, 10)
    assert all(not page.extracted_text.strip() for page in get_document_pages(document_settings, document.id))


def test_partial_document_is_persisted(document_settings, make_pdf):
    document = process_document(document_settings, "long.pdf", make_pdf(("Text",) * 12))
    assert document.status == "partial"
    assert document.total_pages == 12
    assert document.processed_pages == 10
    assert len(get_document_pages(document_settings, document.id)) == 10


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("file.txt", b"%PDF-1.7", "extensão"),
        ("file.pdf", b"invalid signature", "Assinatura"),
        ("file.pdf", b"", "vazio"),
        ("file.pdf", b"%PDF-1.7\ninvalid", "inválido"),
    ],
)
def test_invalid_upload_leaves_no_files_or_records(document_settings, name, content, message):
    with pytest.raises(ValueError, match=message):
        process_document(document_settings, name, content)
    assert list_documents(document_settings) == []
    assert list(document_settings.uploads_dir.iterdir()) == []


def test_file_size_limit(document_settings):
    content = b"%PDF-" + b" " * (MAX_FILE_SIZE_BYTES - 5)
    validate_pdf_upload("exact.pdf", content)
    with pytest.raises(ValueError, match="10 MB"):
        process_document(document_settings, "too-large.pdf", content + b" ")
    assert list_documents(document_settings) == []
    assert list(document_settings.uploads_dir.iterdir()) == []


@pytest.mark.parametrize("count", [0, 4])
def test_batch_size_limit_has_no_side_effects(document_settings, make_pdf, count):
    with pytest.raises(ValueError, match="1 a 3"):
        process_documents(document_settings, [("file.pdf", make_pdf())] * count)
    assert list_documents(document_settings) == []
    assert list(document_settings.uploads_dir.iterdir()) == []


def test_batch_processes_valid_files_despite_an_invalid_file(document_settings, make_pdf):
    results = process_documents(document_settings, [
        ("first.pdf", make_pdf()), ("invalid.pdf", b"bad"), ("last.pdf", make_pdf(("Last",)))
    ])
    assert results[0].document is not None
    assert results[1].error is not None
    assert results[2].document is not None
    assert len(list_documents(document_settings)) == 2


def test_database_failure_rolls_back_metadata_pages_and_removes_pdf(document_settings, make_pdf):
    def fail_insert(connection, document_id, pages):
        connection.execute(
            "INSERT INTO document_pages (document_id, page_number, extracted_text) VALUES (?, ?, ?)",
            (document_id, 1, "temporary"),
        )
        raise sqlite3.IntegrityError("private database detail")

    with patch("services.document_service.repository.insert_pages", side_effect=fail_insert):
        results = process_documents(document_settings, [("file.pdf", make_pdf())])
    assert "Não foi possível salvar" in results[0].error
    assert "private" not in results[0].error
    assert list_documents(document_settings) == []
    assert list(document_settings.uploads_dir.iterdir()) == []
    with get_connection(document_settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM document_pages").fetchone()[0] == 0


def test_upgrade_from_stage_one_preserves_metadata(tmp_path):
    settings = Settings(database_path=tmp_path / "legacy.db", uploads_dir=tmp_path / "uploads")
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.executemany("INSERT INTO app_metadata VALUES (?, ?)", [("schema_version", "1"), ("custom", "preserved")])
    initialize_workspace(settings)
    initialize_workspace(settings)
    assert list_documents(settings) == []
    with get_connection(settings.database_path) as connection:
        assert dict(connection.execute("SELECT key, value FROM app_metadata").fetchall()) == {
            "schema_version": "4", "custom": "preserved"
        }
