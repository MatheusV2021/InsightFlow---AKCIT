"""Testes de navegação e inicialização sem serviços externos."""

from unittest.mock import patch
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from config import BASE_DIR, Settings
from services.document_service import list_documents, process_document


@pytest.fixture
def app_settings(tmp_path):
    return Settings(database_path=tmp_path / "test.db", uploads_dir=tmp_path / "uploads")


@pytest.mark.parametrize(
    ("page_path", "title"),
    [("dashboard", "Dashboard"), ("documents", "Documentos"), ("analyses", "Análises"), ("assistant", "Assistente IA")],
)
def test_pages_render_without_api_key(app_settings, page_path, title):
    with patch("config.get_settings", return_value=app_settings):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        if page_path != "dashboard":
            app.switch_page(f"pages/{page_path}.py").run()
        assert not app.exception
        assert not app.error
        assert app.title[0].value == title
        assert len(app.info) == 1
        assert app_settings.database_path.is_file()


def test_storage_error_has_friendly_message(app_settings):
    with patch("config.get_settings", return_value=app_settings), patch(
        "services.document_service.initialize_workspace", side_effect=OSError("private detail")
    ):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert len(app.error) == 1
    assert "Não foi possível inicializar" in app.error[0].value
    assert "private detail" not in app.error[0].value


def test_upload_button_saves_text_and_reruns_do_not_duplicate(document_settings, make_pdf):
    content = make_pdf(("Saved first page <script>alert(1)</script> & source", "Saved second page"))
    uploaded_file = SimpleNamespace(name="contract.pdf", getvalue=lambda: content)

    def uploader(*args, **kwargs):
        return [uploaded_file] if kwargs["key"] == "document_uploads_0" else []

    with patch("config.get_settings", return_value=document_settings), patch(
        "streamlit.file_uploader", side_effect=uploader
    ):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/documents.py").run()
        assert list_documents(document_settings) == []
        app.button[0].click().run()
        assert not app.exception
        assert not app.error
        assert len(app.success) == 1
        assert len(list_documents(document_settings)) == 1
        assert app.selectbox[1].value == 1
        assert any("Saved first page" in element.value for element in app.get("html"))
        assert any("&lt;script&gt;alert(1)&lt;/script&gt; &amp; source" in element.value for element in app.get("html"))
        assert not any("<script>" in element.value for element in app.get("html"))
        app.selectbox[1].set_value(2).run()
        assert any("Saved second page" in element.value for element in app.get("html"))
        app.run()
        app.switch_page("pages/dashboard.py").run()
        app.switch_page("pages/documents.py").run()
        assert not app.exception
        assert len(list_documents(document_settings)) == 1
        assert app.button[0].disabled

    with patch("config.get_settings", return_value=document_settings):
        restarted_app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        restarted_app.switch_page("pages/documents.py").run()
        assert not restarted_app.exception
        assert len(restarted_app.dataframe[0].value) == 1
        assert restarted_app.selectbox[1].options == ["Página 1", "Página 2"]


def test_upload_limit_is_shown_and_button_is_disabled(document_settings):
    with patch("config.get_settings", return_value=document_settings), patch(
        "streamlit.file_uploader", return_value=[object()] * 4
    ):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/documents.py").run()
        assert not app.exception
        assert "no máximo 3" in app.error[0].value
        assert app.button[0].disabled
        assert list_documents(document_settings) == []


def test_partial_scan_shows_both_limit_and_no_text_messages(document_settings, make_pdf):
    process_document(document_settings, "scan.pdf", make_pdf(("",) * 11))
    with patch("config.get_settings", return_value=document_settings):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/documents.py").run()
        assert not app.exception
        assert any("parcial" in warning.value for warning in app.warning)
        assert any("Nenhum texto extraível" in warning.value for warning in app.warning)
        assert len(app.selectbox[1].options) == 10
