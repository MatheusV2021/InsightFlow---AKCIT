"""Queries parametrizadas para documentos e suas páginas."""

import sqlite3
import json
from pathlib import Path

from database.db import get_connection
from models.schemas import Analysis, Document, DocumentPage, Evidence, Finding, SourcePage


def insert_document(connection: sqlite3.Connection, document: Document) -> None:
    """Insere metadados na transação controlada pelo serviço."""
    connection.execute(
        """
        INSERT INTO documents
            (id, original_filename, stored_filename, uploaded_at,
             total_pages, processed_pages, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document.id, document.original_filename, document.stored_filename,
            document.uploaded_at.isoformat(), document.total_pages,
            document.processed_pages, document.status,
        ),
    )


def insert_pages(
    connection: sqlite3.Connection, document_id: str, pages: list[DocumentPage]
) -> None:
    """Insere todas as páginas na mesma transação dos metadados."""
    connection.executemany(
        """
        INSERT INTO document_pages (document_id, page_number, extracted_text)
        VALUES (?, ?, ?)
        """,
        [(document_id, page.page_number, page.extracted_text) for page in pages],
    )


def list_documents(database_path: Path) -> list[Document]:
    """Lista documentos do envio mais recente ao mais antigo."""
    with get_connection(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM documents ORDER BY uploaded_at DESC, id DESC"
        ).fetchall()
    return [Document.model_validate(dict(row)) for row in rows]


def get_document(database_path: Path, document_id: str) -> Document | None:
    """Recupera um documento pelo ID ou retorna None."""
    with get_connection(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    return Document.model_validate(dict(row)) if row is not None else None


def get_document_pages(database_path: Path, document_id: str) -> list[DocumentPage]:
    """Recupera texto e numeração original em ordem de página."""
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT page_number, extracted_text FROM document_pages
            WHERE document_id = ? ORDER BY page_number
            """,
            (document_id,),
        ).fetchall()
    return [DocumentPage.model_validate(dict(row)) for row in rows]


def save_analysis(database_path: Path, analysis: Analysis, input_hash: str) -> None:
    """Salva análise, associações, achados e evidências na mesma transação."""
    with get_connection(database_path) as connection:
        connection.execute(
            """INSERT INTO analyses
            (id, input_hash, created_at, model, summary, warnings_json, discarded_findings, is_demo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (analysis.id, input_hash, analysis.created_at.isoformat(), analysis.model,
             analysis.summary, json.dumps(analysis.warnings, ensure_ascii=False), analysis.discarded_findings, int(analysis.is_demo)),
        )
        connection.executemany(
            "INSERT INTO analysis_documents (analysis_id, document_id) VALUES (?, ?)",
            [(analysis.id, document_id) for document_id in analysis.document_ids],
        )
        for finding in analysis.findings:
            connection.execute(
                """INSERT INTO findings
                (id, analysis_id, title, description, category, severity, recommended_action)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (finding.id, analysis.id, finding.title, finding.description,
                 finding.category, finding.severity, finding.recommended_action),
            )
            connection.executemany(
                """INSERT INTO finding_evidence
                (finding_id, document_id, filename, page_number, quote) VALUES (?, ?, ?, ?, ?)""",
                [(finding.id, item.document_id, item.filename, item.page_number, item.quote)
                 for item in finding.evidence],
            )


def list_analyses(database_path: Path, demo_mode: bool | None = None) -> list[dict]:
    """Lista cabeçalhos sem carregar textos ou chamar a IA."""
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """SELECT id, created_at, model, summary, is_demo FROM analyses
            WHERE (? IS NULL OR is_demo = ?) ORDER BY created_at DESC, id DESC""",
            (demo_mode, demo_mode),
        ).fetchall()
    return [dict(row) for row in rows]


def get_evidence(database_path: Path, finding_id: str) -> list[Evidence]:
    """Consulta as citações persistidas de um achado."""
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """SELECT document_id, filename, page_number, quote FROM finding_evidence
            WHERE finding_id = ? ORDER BY id""", (finding_id,),
        ).fetchall()
    return [Evidence.model_validate(dict(row)) for row in rows]


def get_analysis(database_path: Path, analysis_id: str) -> Analysis | None:
    """Recupera uma análise completa com seus achados e citações."""
    with get_connection(database_path) as connection:
        row = connection.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if row is None:
            return None
        document_rows = connection.execute(
            "SELECT document_id FROM analysis_documents WHERE analysis_id = ? ORDER BY document_id",
            (analysis_id,),
        ).fetchall()
        finding_rows = connection.execute(
            """SELECT id, title, description, category, severity, recommended_action FROM findings
            WHERE analysis_id = ? ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id""",
            (analysis_id,),
        ).fetchall()
    return Analysis(
        id=row["id"], created_at=row["created_at"], model=row["model"],
        document_ids=[item["document_id"] for item in document_rows],
        summary=row["summary"], warnings=json.loads(row["warnings_json"]),
        discarded_findings=row["discarded_findings"],
        is_demo=bool(row["is_demo"]),
        findings=[Finding(**dict(item), evidence=get_evidence(database_path, item["id"])) for item in finding_rows],
    )


def find_analysis_id(database_path: Path, input_hash: str) -> str | None:
    """Busca resultado já salvo para a mesma entrada e versão do fluxo."""
    with get_connection(database_path) as connection:
        row = connection.execute("SELECT id FROM analyses WHERE input_hash = ?", (input_hash,)).fetchone()
    return row["id"] if row is not None else None


def list_risks(database_path: Path, analysis_id: str) -> list[Finding]:
    """Lista possíveis riscos e inconsistências por prioridade."""
    analysis = get_analysis(database_path, analysis_id)
    return [item for item in analysis.findings if item.category in {"risk", "inconsistency"}] if analysis else []


def get_dashboard_counts(database_path: Path, demo_mode: bool | None = None) -> dict[str, int]:
    """Conta registros reais e limitações dos documentos sem carregar os PDFs."""
    with get_connection(database_path) as connection:
        row = connection.execute(
            """SELECT
                (SELECT COUNT(*) FROM documents) AS document_count,
                (SELECT COUNT(*) FROM analyses WHERE (? IS NULL OR is_demo = ?)) AS analysis_count,
                (SELECT COUNT(*) FROM documents WHERE processed_pages < total_pages) AS partial_document_count,
                (SELECT COUNT(*) FROM documents WHERE status = 'no_text') AS no_text_document_count
            """, (demo_mode, demo_mode),
        ).fetchone()
    return dict(row)


def get_selected_document_pages(database_path: Path, document_ids: list[str]) -> list[SourcePage]:
    """Consulta páginas somente dos IDs selecionados, com seus nomes originais."""
    if not document_ids:
        return []
    placeholders = ", ".join("?" for _ in document_ids)
    with get_connection(database_path) as connection:
        rows = connection.execute(
            f"""SELECT d.id AS document_id, d.original_filename AS filename,
                p.page_number, p.extracted_text AS text
                FROM documents d JOIN document_pages p ON p.document_id = d.id
                WHERE d.id IN ({placeholders}) ORDER BY d.id, p.page_number""",
            document_ids,
        ).fetchall()
    return [SourcePage.model_validate(dict(row)) for row in rows]
