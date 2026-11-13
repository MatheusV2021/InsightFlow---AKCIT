"""Demonstração local previsível, com PDFs reais e proibição de acesso à API."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from config import BASE_DIR, Settings
from database import repository
from database.db import get_connection
from models.schemas import AnalystOutput
from scripts.create_sample_pdfs import create_sample_pdfs
from services.analysis_service import analyze_documents, evidence_matches, get_analysis, list_analyses, prepare_sources
from services.chat_service import ask_question
from services.dashboard_service import get_dashboard_data
from services.document_service import initialize_workspace, process_documents
from services.llm_service import LLMError, request_structured


@pytest.fixture
def demo_setup(document_settings, tmp_path):
    settings = document_settings.model_copy(update={"demo_mode": True})
    paths = create_sample_pdfs(tmp_path / "samples")
    results = process_documents(settings, [(path.name, path.read_bytes()) for path in paths])
    assert all(result.document is not None for result in results)
    return settings, [result.document.id for result in results], paths


def test_generated_pdfs_are_fictional_readable_and_repeatable(demo_setup):
    settings, ids, paths = demo_setup
    assert len(paths) == 3
    create_sample_pdfs(paths[0].parent)
    sources, warnings = prepare_sources(settings, ids)
    assert len(sources) == 3 and not warnings
    assert all(source.page_number == 1 and "DOCUMENTO FICTÍCIO" in source.text for source in sources)
    assert any("10 dias corridos" in source.text for source in sources)
    assert any("30 dias corridos" in source.text for source in sources)


def test_demo_analysis_persists_valid_evidence_and_reuses_result(demo_setup):
    settings, ids, _ = demo_setup
    with patch("services.analysis_service.request_structured", side_effect=AssertionError("No API in demo")) as model:
        analysis = analyze_documents(settings, ids)
        assert analyze_documents(settings, list(reversed(ids))).id == analysis.id
        restarted = Settings(database_path=settings.database_path, uploads_dir=settings.uploads_dir, demo_mode=True)
        initialize_workspace(restarted)
        assert get_analysis(restarted, analysis.id) == analysis
        model.assert_not_called()
    assert analysis.is_demo
    assert analysis.model == "demo-local-v1"
    assert len(analysis.findings) == 4
    sources, _ = prepare_sources(settings, ids)
    assert all(evidence_matches(finding.evidence, sources) for finding in analysis.findings)
    assert any("exceção" in finding.description for finding in analysis.findings)
    data = get_dashboard_data(settings)
    assert data["analysis_count"] == 1
    assert data["risk_count"] == 2
    assert data["high_priority_count"] == 1
    assert data["limited_analysis_count"] == 0


def test_normal_and_demo_results_do_not_mix(demo_setup):
    settings, ids, _ = demo_setup
    demo = analyze_documents(settings, ids)
    normal = settings.model_copy(update={"demo_mode": False})
    assert get_analysis(normal, demo.id) is None
    assert not list_analyses(normal)
    assert get_dashboard_data(normal)["risk_count"] == 0
    with patch("services.analysis_service.request_structured", return_value=AnalystOutput(facts=[])) as model:
        real = analyze_documents(normal, ids)
        model.assert_called_once()
    assert not real.is_demo and real.model == settings.openai_model
    assert real.findings == []
    assert get_analysis(settings, real.id) is None
    assert [row["id"] for row in list_analyses(normal)] == [real.id]
    assert [row["id"] for row in list_analyses(settings)] == [demo.id]
    assert get_dashboard_data(normal)["analysis_count"] == 1
    assert get_dashboard_data(normal)["risk_count"] == 0


def test_demo_refuses_unrelated_or_modified_pdf(document_settings, make_pdf):
    from services.document_service import process_document
    settings = document_settings.model_copy(update={"demo_mode": True})
    document = process_document(settings, "FICTICIO_01_contrato_fornecedor.pdf", make_pdf(("Unrelated contract payment data",)))
    with patch("services.analysis_service.request_structured") as model:
        with pytest.raises(ValueError, match="PDF fictício"):
            analyze_documents(settings, [document.id])
        model.assert_not_called()
    assert not list_analyses(settings)


def test_modified_sample_text_cannot_receive_canned_findings(demo_setup):
    settings, ids, _ = demo_setup
    with get_connection(settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = extracted_text || ? WHERE document_id = ?", (" Alteração não prevista.", ids[0]))
    with pytest.raises(ValueError, match="PDF fictício"):
        analyze_documents(settings, ids)
    assert not list_analyses(settings)


def test_shared_client_blocks_api_even_with_key_in_demo():
    with patch("services.llm_service.OpenAI") as client:
        with pytest.raises(LLMError, match="desativada"):
            request_structured(Settings(demo_mode=True, openai_api_key="fake-key"), "instructions", "payload", AnalystOutput)
        client.assert_not_called()


def test_demo_chat_is_explicitly_local_and_does_not_call_model(demo_setup):
    settings, ids, _ = demo_setup
    with patch("services.chat_service.request_structured", side_effect=AssertionError("No API in demo")) as model:
        response = ask_question(settings, "Qual o prazo de pagamento?", ids)
        model.assert_not_called()
    assert response.is_demo
    assert "sem geração por IA" in response.answer
    assert response.evidence
    sources = repository.get_selected_document_pages(settings.database_path, ids)
    assert evidence_matches(response.evidence, sources)


def test_migration_from_stage_five_marks_existing_analysis_as_real(document_settings):
    # Reproduz a tabela antiga sem a coluna adicionada nesta etapa.
    with get_connection(document_settings.database_path) as connection:
        connection.execute("ALTER TABLE analyses DROP COLUMN is_demo")
        connection.execute("UPDATE app_metadata SET value = ? WHERE key = ?", ("3", "schema_version"))
        connection.execute("INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?)",
                           ("legacy", "old-hash", "2026-11-13T12:00:00+00:00", "old-model", "summary", "[]", 0))
    initialize_workspace(document_settings)
    initialize_workspace(document_settings)
    assert repository.get_analysis(document_settings.database_path, "legacy").is_demo is False
    assert not repository.list_analyses(document_settings.database_path, True)


def test_demo_user_flow_and_new_session_without_api(demo_setup):
    settings, ids, _ = demo_setup
    with patch("config.get_settings", return_value=settings), patch(
        "services.analysis_service.request_structured", side_effect=AssertionError("No model")
    ), patch("services.chat_service.request_structured", side_effect=AssertionError("No model")):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/documents.py").run()
        assert not app.exception
        app.switch_page("pages/analyses.py").run()
        app.multiselect[0].set_value(ids).run()
        app.button[0].click().run()
        assert not app.exception and not app.error
        assert any("ANÁLISE SIMULADA" in warning.value for warning in app.warning)
        assert len(app.expander) == 4
        app.switch_page("pages/dashboard.py").run()
        assert [metric.value for metric in app.metric] == ["3", "1", "2", "1"]
        assert len(app.get("plotly_chart")) == 2
        app.switch_page("pages/assistant.py").run()
        app.multiselect[0].set_value(ids).run()
        app.chat_input[0].set_value("Qual o prazo de pagamento?").run()
        assert not app.exception and not app.error
        assert len(app.get("chat_message")) == 2
        restarted = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        assert not restarted.exception
        assert [metric.value for metric in restarted.metric] == ["3", "1", "2", "1"]
        settings.demo_mode = False
        restarted.run()
        assert not restarted.exception
        assert [metric.value for metric in restarted.metric] == ["3", "0", "0", "0"]
        assert not restarted.warning
        restarted.switch_page("pages/analyses.py").run()
        assert not restarted.exception
        assert not restarted.expander
        assert not any("ANÁLISE SIMULADA" in warning.value for warning in restarted.warning)
