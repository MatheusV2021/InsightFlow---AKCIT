"""Análise com respostas simuladas, sem tráfego ou consumo de tokens."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from config import MAX_ANALYSIS_TEXT_CHARS, Settings
from database import repository
from database.db import get_connection
from models.schemas import AnalystOutput, AuditorOutput, Evidence, FindingDraft, SourcePage
from services.analysis_service import (
    analyze_documents, evidence_matches, get_analysis, list_analyses, list_risks, prepare_sources,
)
from services.document_service import process_document
from services.llm_service import LLMError


@pytest.fixture
def analysis_inputs(document_settings, make_pdf):
    texts = ["Contract ACME: payment within 30 days.", "Contract ACME: payment within 60 days."]
    documents = [process_document(document_settings, f"contract-{index}.pdf", make_pdf((text,)))
                 for index, text in enumerate(texts)]
    evidence = [Evidence(document_id=document.id, filename=document.original_filename,
                         page_number=1, quote=text) for document, text in zip(documents, texts)]
    analyst = AnalystOutput(facts=[{
        "category": "deadline", "description": item.quote, "evidence": [item],
    } for item in evidence])
    draft = FindingDraft(
        title="Possível divergência no prazo", description="Os documentos podem indicar prazos diferentes para o mesmo contrato.",
        category="inconsistency", severity="high", recommended_action="Solicitar revisão e confirmar qual prazo contratual se aplica.",
        evidence=evidence,
    )
    return [document.id for document in documents], analyst, AuditorOutput(findings=[draft])


def test_structured_schema_rejects_invalid_severity_and_missing_evidence(analysis_inputs):
    _, _, audit = analysis_inputs
    data = audit.findings[0].model_dump()
    with pytest.raises(ValidationError):
        FindingDraft.model_validate({**data, "severity": "critical"})
    with pytest.raises(ValidationError):
        FindingDraft.model_validate({**data, "evidence": []})
    with pytest.raises(ValidationError):
        FindingDraft.model_validate({**data, "category": "proven_violation"})


def test_analysis_persistence_evidence_and_reuse_without_key(document_settings, analysis_inputs):
    ids, analyst, audit = analysis_inputs
    with patch("services.analysis_service.request_structured", side_effect=[analyst, audit]) as model:
        analysis = analyze_documents(document_settings, ids)
        assert model.call_count == 2
        assert model.call_args_list[0].args[3] is AnalystOutput
        assert model.call_args_list[1].args[3] is AuditorOutput
    assert len(analysis.findings) == 1
    assert len(repository.get_evidence(document_settings.database_path, analysis.findings[0].id)) == 2
    assert len(repository.list_risks(document_settings.database_path, analysis.id)) == 1
    assert get_analysis(document_settings, analysis.id) == analysis
    assert list_risks(document_settings, analysis.id) == analysis.findings
    assert len(list_analyses(document_settings)) == 1
    restarted = Settings(database_path=document_settings.database_path, uploads_dir=document_settings.uploads_dir)
    with patch("services.analysis_service.request_structured", side_effect=AssertionError("No API on reuse")):
        assert analyze_documents(restarted, list(reversed(ids))) == analysis
        assert get_analysis(restarted, analysis.id) == analysis
    assert repository.get_analysis(document_settings.database_path, "' OR 1=1 --") is None


@pytest.mark.parametrize(("field", "value"), [
    ("document_id", "missing"), ("filename", "wrong.pdf"), ("page_number", 2),
    ("quote", "Text that does not exist"), ("quote", "   "),
])
def test_evidence_requires_all_coordinates_and_literal_quote(field, value):
    source = SourcePage(document_id="doc", filename="file.pdf", page_number=1, text="Payment within 30 days.\nNext line")
    evidence = Evidence(document_id="doc", filename="file.pdf", page_number=1, quote="Payment within 30 days.")
    assert evidence_matches([evidence], [source])
    assert not evidence_matches([evidence.model_copy(update={field: value})], [source])
    assert not evidence_matches([], [source])


def test_invalid_auditor_evidence_discards_whole_finding(document_settings, analysis_inputs):
    ids, analyst, audit = analysis_inputs
    audit.findings[0].evidence[1].quote = "Unverifiable text"
    with patch("services.analysis_service.request_structured", side_effect=[analyst, audit]):
        analysis = analyze_documents(document_settings, ids)
    assert not analysis.findings
    assert analysis.discarded_findings == 1
    assert "0 achado" in analysis.summary
    assert "Unverifiable" not in analysis.model_dump_json()


def test_inconsistency_requires_two_different_documents(document_settings, analysis_inputs):
    ids, analyst, audit = analysis_inputs
    audit.findings[0].evidence = [audit.findings[0].evidence[0]]
    with patch("services.analysis_service.request_structured", side_effect=[analyst, audit]):
        analysis = analyze_documents(document_settings, ids)
    assert not analysis.findings
    assert analysis.discarded_findings == 1


def test_analyst_facts_with_bad_evidence_are_not_sent_to_auditor(document_settings, analysis_inputs):
    ids, analyst, audit = analysis_inputs
    analyst.facts[0].evidence[0].filename = "wrong.pdf"
    with patch("services.analysis_service.request_structured", side_effect=[analyst, audit]) as model:
        analysis = analyze_documents(document_settings, ids)
    sent_facts = AnalystOutput.model_validate_json(model.call_args_list[1].args[2])
    assert len(sent_facts.facts) == 1
    assert sent_facts.facts[0].evidence[0].document_id == ids[1]
    assert not analysis.findings
    assert analysis.warnings


def test_empty_analyst_skips_second_call(document_settings, analysis_inputs):
    ids, _, _ = analysis_inputs
    with patch("services.analysis_service.request_structured", return_value=AnalystOutput(facts=[])) as model:
        analysis = analyze_documents(document_settings, ids)
    assert model.call_count == 1
    assert not analysis.findings
    assert get_analysis(document_settings, analysis.id) is not None


def test_priorities_are_sorted_and_counted_from_verified_findings(document_settings, analysis_inputs):
    ids, analyst, audit = analysis_inputs
    template = audit.findings[0]
    audit.findings = [template.model_copy(update={"severity": severity}) for severity in ("low", "high", "medium")]
    with patch("services.analysis_service.request_structured", side_effect=[analyst, audit]):
        analysis = analyze_documents(document_settings, ids)
    assert [finding.severity for finding in analysis.findings] == ["high", "medium", "low"]
    assert "3 possível" in analysis.summary
    assert "1 de prioridade alta" in analysis.summary
    assert [finding.severity for finding in get_analysis(document_settings, analysis.id).findings] == ["high", "medium", "low"]


@pytest.mark.parametrize("ids", [[], ["missing"], ["a", "b", "c", "d"], ["same", "same"]])
def test_invalid_document_selection_makes_no_call(document_settings, ids):
    with patch("services.analysis_service.request_structured") as model:
        with pytest.raises(ValueError):
            analyze_documents(document_settings, ids)
        model.assert_not_called()
    assert not list_analyses(document_settings)


def test_insufficient_text_makes_no_call(document_settings, make_pdf):
    document = process_document(document_settings, "blank.pdf", make_pdf(("",)))
    with patch("services.analysis_service.request_structured") as model:
        with pytest.raises(ValueError, match="insuficiente"):
            analyze_documents(document_settings, [document.id])
        model.assert_not_called()


def test_text_budget_and_partial_pages_warnings(document_settings, make_pdf):
    # O texto persistido pode conter páginas muito densas, sem gerar um PDF enorme na fixture.
    documents = [process_document(document_settings, f"long-{index}.pdf", make_pdf(("Contract text for analysis.",) * 11)) for index in range(3)]
    with get_connection(document_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ?", ("A" * MAX_ANALYSIS_TEXT_CHARS,))
    sources, warnings = prepare_sources(document_settings, [document.id for document in documents])
    assert sum(len(source.text) for source in sources) <= MAX_ANALYSIS_TEXT_CHARS
    assert {source.document_id for source in sources} == {document.id for document in documents}
    assert len([warning for warning in warnings if "caracteres" in warning]) == 3
    assert len([warning for warning in warnings if "páginas" in warning]) == 3


def test_api_failure_does_not_save_analysis(document_settings, analysis_inputs):
    ids, analyst, _ = analysis_inputs
    with patch("services.analysis_service.request_structured", side_effect=[analyst, LLMError("Falha de conexão")]):
        with pytest.raises(LLMError):
            analyze_documents(document_settings, ids)
    assert not list_analyses(document_settings)


def test_saved_evidence_is_revalidated_before_display(document_settings, analysis_inputs):
    ids, analyst, audit = analysis_inputs
    with patch("services.analysis_service.request_structured", side_effect=[analyst, audit]):
        analysis = analyze_documents(document_settings, ids)
    with get_connection(document_settings.database_path) as connection:
        connection.execute("UPDATE document_pages SET extracted_text = ? WHERE document_id = ?", ("Changed source", ids[0]))
    loaded = get_analysis(document_settings, analysis.id)
    assert not loaded.findings
    assert "0 achado" in loaded.summary
    assert loaded.discarded_findings == 1
    assert not list_risks(document_settings, analysis.id)


def test_analysis_transaction_rolls_back_on_invalid_evidence(document_settings, analysis_inputs):
    ids, analyst, audit = analysis_inputs
    with patch("services.analysis_service.request_structured", side_effect=[analyst, audit]):
        analysis = analyze_documents(document_settings, ids)
    analysis.id = "rollback-test"
    analysis.findings[0].id = "new-finding"
    analysis.findings[0].evidence[0].page_number = 999
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_analysis(document_settings.database_path, analysis, "rollback-key")
    assert repository.get_analysis(document_settings.database_path, analysis.id) is None
    assert len(list_analyses(document_settings)) == 1


def test_analysis_page_explicit_button_reruns_and_new_session(document_settings, analysis_inputs):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR

    ids, analyst, audit = analysis_inputs
    with patch("config.get_settings", return_value=document_settings), patch(
        "services.analysis_service.request_structured", side_effect=[analyst, audit]
    ) as model:
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/analyses.py").run()
        app.multiselect[0].set_value(ids).run()
        model.assert_not_called()
        app.button[0].click().run()
        assert not app.exception
        assert not app.error
        assert model.call_count == 2
        assert len(app.expander) == 1
        assert "Ver trechos originais" in app.expander[0].label
        assert not app.expander[0].proto.expanded
        assert any("Possível inconsistência" in element.value for element in app.get("html"))
        assert len(app.text) == 2
        assert all(any(item.quote in element.value for element in app.get("html")) for item in audit.findings[0].evidence)
        app.radio[0].set_value("Prazos").run()
        assert not app.expander
        assert any("Nenhum achado" in item.value for item in app.info)
        app.radio[0].set_value("Riscos").run()
        assert len(app.expander) == 1
        assert model.call_count == 2
        app.run()
        app.button[0].click().run()
        assert not app.exception
        assert model.call_count == 2
        assert len(list_analyses(document_settings)) == 1

    with patch("config.get_settings", return_value=document_settings), patch(
        "services.analysis_service.request_structured", side_effect=AssertionError("No model on restart")
    ) as model:
        restarted = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        restarted.switch_page("pages/analyses.py").run()
        assert not restarted.exception
        assert len(restarted.expander) == 1
        assert len(restarted.text) == 2
        model.assert_not_called()


def test_analysis_page_missing_key_has_message_without_traceback(document_settings, analysis_inputs):
    from streamlit.testing.v1 import AppTest
    from config import BASE_DIR

    ids, _, _ = analysis_inputs
    with patch("config.get_settings", return_value=document_settings):
        app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=15).run()
        app.switch_page("pages/analyses.py").run()
        app.multiselect[0].set_value(ids).run()
        app.button[0].click().run()
    assert not app.exception
    assert len(app.error) == 1
    assert "OPENAI_API_KEY" in app.error[0].value
    assert not list_analyses(document_settings)
