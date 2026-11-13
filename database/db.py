"""Conexão e inicialização idempotente do SQLite."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def get_connection(database_path: Path) -> Iterator[sqlite3.Connection]:
    """Abre uma transação, confirma ou desfaz alterações e fecha a conexão."""
    connection = sqlite3.connect(database_path, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(database_path: Path) -> None:
    """Cria o diretório, o banco e os metadados iniciais sem apagar dados."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO app_metadata (key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                uploaded_at TEXT NOT NULL,
                total_pages INTEGER NOT NULL CHECK (total_pages >= 1),
                processed_pages INTEGER NOT NULL
                    CHECK (processed_pages >= 1 AND processed_pages <= total_pages),
                status TEXT NOT NULL CHECK (status IN ('processed', 'partial', 'no_text'))
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS document_pages (
                id INTEGER PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL CHECK (page_number >= 1),
                extracted_text TEXT NOT NULL,
                UNIQUE (document_id, page_number)
            )
            """
        )
        connection.execute(
            "UPDATE app_metadata SET value = ? WHERE key = ? AND value = ?",
            ("2", "schema_version", "1"),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                input_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                model TEXT NOT NULL,
                summary TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                discarded_findings INTEGER NOT NULL CHECK (discarded_findings >= 0)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_documents (
                analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                document_id TEXT NOT NULL REFERENCES documents(id),
                PRIMARY KEY (analysis_id, document_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('obligation', 'deadline', 'risk', 'inconsistency')),
                severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
                recommended_action TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS finding_evidence (
                id INTEGER PRIMARY KEY,
                finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
                document_id TEXT NOT NULL REFERENCES documents(id),
                filename TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                quote TEXT NOT NULL,
                FOREIGN KEY (document_id, page_number)
                    REFERENCES document_pages(document_id, page_number)
            )
            """
        )
        connection.execute(
            "UPDATE app_metadata SET value = ? WHERE key = ? AND value = ?",
            ("3", "schema_version", "2"),
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(analyses)")}
        if "is_demo" not in columns:
            connection.execute("ALTER TABLE analyses ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0, 1))")
        connection.execute(
            "UPDATE app_metadata SET value = ? WHERE key = ? AND value = ?",
            ("4", "schema_version", "3"),
        )
