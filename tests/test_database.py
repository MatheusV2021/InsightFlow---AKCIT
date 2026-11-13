"""Verificações da persistência SQLite em diretórios temporários."""

import sqlite3

import pytest

from config import Settings
from database.db import get_connection
from services.document_service import initialize_workspace


def test_initialization_preserves_existing_data(tmp_path):
    settings = Settings(database_path=tmp_path / "data" / "test.db", uploads_dir=tmp_path / "uploads")
    initialize_workspace(settings)
    with get_connection(settings.database_path) as connection:
        connection.execute("INSERT INTO app_metadata (key, value) VALUES (?, ?)", ("test", "preserved"))
    initialize_workspace(settings)
    assert settings.uploads_dir.is_dir()
    with get_connection(settings.database_path) as connection:
        rows = connection.execute("SELECT key, value FROM app_metadata").fetchall()
        assert {row["key"]: row["value"] for row in rows} == {"schema_version": "4", "test": "preserved"}
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_failed_transaction_is_rolled_back_and_closed(tmp_path):
    settings = Settings(database_path=tmp_path / "test.db", uploads_dir=tmp_path / "uploads")
    initialize_workspace(settings)
    with pytest.raises(RuntimeError):
        with get_connection(settings.database_path) as connection:
            connection.execute("INSERT INTO app_metadata (key, value) VALUES (?, ?)", ("rollback", "value"))
            raise RuntimeError("Simulação de falha")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with get_connection(settings.database_path) as connection:
        assert connection.execute("SELECT value FROM app_metadata WHERE key = ?", ("rollback",)).fetchone() is None
