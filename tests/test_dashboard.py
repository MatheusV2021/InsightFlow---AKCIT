"""Indicadores e filtros com histórico real de teste no SQLite, sem IA."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from config import BASE_DIR
from database import repository
from database.db import get_connection
from models.schemas import Analysis, Evidence, Finding
from services.analysis_service import filter_analysis_findings, get_analysis
from services.dashboard_service import get_dashboard_data
from services.document_service import process_document


@pytest.fixture
def dashboard_history(document_settings, make_pdf):
    texts = ["Contract ACME: payment within 30 days.", "Contract ACME: payment within 60 days."]
    documents = [process_document(document_settings, f"contract-{index}.pdf", make_pdf((text,)))
                 for index, text in enumerate(texts)]
    evidence = [Evidence(document_id=document.id, filename=document.original_filename,
                         page_number=1, quote=text) for document, text in zip(documents, texts)]
    findings = [
        Finding(id=str(uuid4()), title=title, description="Descrição para revisão documental.",
                category=category, severity=severity, recommended_action=f"Revisar: {title}.", evidence=references)
        for title, category, severity, references in [
            ("Risco potencial", "risk", "high", evidence),
            ("Possível conflito", "inconsistency", "medium", evidence),
            ("Obrigação contratual", "obligation", "high", evidence[:1]),
            ("Prazo contratual", "deadline", "low", evidence[:1]),
        ]
    ]
    created_at = datetime.now(timezone.utc)
    first = Analysis(
        id=str(uuid4()), created_at=created_at, model="test-model", document_ids=sorted(document.id for document in documents),
        summary="Resumo salvo", warnings=[], discarded_findings=0, findings=findings,
    )
    second = first.model_copy(update={
        "id": str(uuid4()), "created_at": created_at + timedelta(seconds=1),
        "findings": [findings[0].model_copy(update={"id": str(uuid4()), "severity": "low", "evidence": evidence[:1]})],
    })
    repository.save_analysis(document_settings.database_path, first, "test-history-one")
    repository.save_analysis(document_settings.database_path, second, "test-history-two")
    return documents, first, second


def test_dashboard_counts_risks_once_per_finding_not_per_evidence(document_settings, dashboard_history):
    data = get_dashboard_data(document_settings)
    assert data["document_count"] == 2
    assert data["analysis_count"] == 2
    assert data["risk_count"] == 3
    assert data["high_priority_count"] == 1
    assert data["risks_by_priority"] == {"high": 1, "medium": 1, "low": 1}
    assert data["risks_by_category"] == {"risk": 2, "inconsistency": 1}
    assert len(data["recommendations"]) == 3
    assert len(data["high_priority_alerts"]) == 1
    assert data["recent_analyses"][0]["id"] == dashboard_history[2].id


def test_dashboard_removes_risks_with_no_longer_matching_evidence(document_settings, dashboard_history):
    documents, _, _ = dashboard_history
    with get_connection(document_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ? WHERE document_id = ?", ("Changed source text", documents[1].id))
    data = get_dashboard_data(document_settings)
    assert data["risk_count"] == 1
    assert data["high_priority_count"] == 0
    assert data["limited_analysis_count"] == 1


def test_empty_dashboard_is_real_zero_even_in_demo_mode(document_settings):
    document_settings.demo_mode = True
    data = get_dashboard_data(document_settings)
    assert document_settings.demo_mode
    assert data["document_count"] == data["analysis_count"] == data["risk_count"] == data["high_priority_count"] == 0
    with patch("config.get_settings", return_value=document_settings):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["0", "0", "0", "0"]
    assert "Envie PDFs" in app.info[0].value
    assert not app.get("plotly_chart")


def test_no_risks_and_incomplete_documents_render_without_fake_alerts(document_settings, make_pdf):
    document = process_document(document_settings, "scan.pdf", make_pdf(("",) * 11))
    analysis = Analysis(
        id=str(uuid4()), created_at=datetime.now(timezone.utc), model="test-model",
        document_ids=[document.id], summary="Sem achados", warnings=["Cobertura limitada"],
        discarded_findings=0, findings=[],
    )
    repository.save_analysis(document_settings.database_path, analysis, "empty-test")
    data = get_dashboard_data(document_settings)
    assert data["partial_document_count"] == data["no_text_document_count"] == 1
    assert data["limited_analysis_count"] == 1
    with patch("config.get_settings", return_value=document_settings):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["1", "1", "0", "0"]
    assert len(app.get("plotly_chart")) == 2
    assert "Nenhum risco" in app.info[0].value
    assert not app.warning


def test_dashboard_rendering_charts_and_restart_never_call_model(document_settings, dashboard_history):
    with patch("config.get_settings", return_value=document_settings), patch(
        "services.analysis_service.request_structured", side_effect=AssertionError("Dashboard must not call AI")
    ) as model:
        for _ in range(2):
            app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
            assert not app.exception
            assert not app.error
            assert [metric.value for metric in app.metric] == ["2", "2", "3", "1"]
            charts = app.get("plotly_chart")
            assert len(charts) == 2
            assert json.loads(charts[0].proto.spec)["data"][0]["y"] == [1, 1, 1]
            assert json.loads(charts[1].proto.spec)["data"][0]["y"] == [2, 1]
            assert len(app.dataframe[0].value) == 2
            assert app.warning[0].value == "Risco potencial"
            app.run()
        model.assert_not_called()


def test_filters_combine_priority_category_and_evidence_document(document_settings, dashboard_history):
    documents, first, _ = dashboard_history
    analysis = get_analysis(document_settings, first.id)
    assert len(filter_analysis_findings(analysis.findings, [], [], None)) == 4
    assert len(filter_analysis_findings(analysis.findings, ["high"], [], None)) == 2
    assert len(filter_analysis_findings(analysis.findings, [], [], documents[1].id)) == 2
    assert len(filter_analysis_findings(analysis.findings, ["high"], ["risk"], documents[1].id)) == 1
    assert not filter_analysis_findings(analysis.findings, ["low"], ["risk"], None)


def test_analysis_filter_widgets_and_navigation_flow(document_settings, dashboard_history):
    documents, first, _ = dashboard_history
    with patch("config.get_settings", return_value=document_settings), patch(
        "services.analysis_service.request_structured", side_effect=AssertionError("Filters must not call AI")
    ) as model:
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/documents.py").run()
        assert not app.exception
        app.switch_page("pages/analyses.py").run()
        app.selectbox[0].set_value(first.id).run()
        assert len(app.expander) == 4
        app.multiselect[1].set_value(["low"]).run()
        app.multiselect[2].set_value(["risk"]).run()
        assert not app.expander
        assert any("filtros" in info.value for info in app.info)
        app.multiselect[1].set_value(["high"]).run()
        app.selectbox[1].set_value(documents[1].id).run()
        assert not app.exception
        assert len(app.expander) == 1
        assert len(app.text) == 2  # O filtro mantém todas as evidências do achado.
        app.switch_page("pages/dashboard.py").run()
        assert not app.exception
        assert [metric.value for metric in app.metric] == ["2", "2", "3", "1"]
        model.assert_not_called()


def test_dashboard_storage_failure_has_no_traceback(document_settings):
    import sqlite3
    with patch("config.get_settings", return_value=document_settings), patch(
        "services.dashboard_service.repository.get_dashboard_counts", side_effect=sqlite3.OperationalError("private detail")
    ):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert len(app.error) == 1
    assert "private detail" not in app.error[0].value
