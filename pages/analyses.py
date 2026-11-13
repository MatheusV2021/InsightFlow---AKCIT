"""Análise explícita de documentos e consulta de resultados persistidos."""

import sqlite3
from datetime import datetime, timedelta, timezone

import streamlit as st

from config import MAX_ANALYSIS_DOCUMENTS, MAX_ANALYSIS_TEXT_CHARS, get_settings
from services.analysis_service import analyze_documents, filter_analysis_findings, get_analysis, list_analyses
from services.document_service import list_documents
from services.llm_service import LLMError
from ui_reading import finding_heading, reading_styles, reading_text

settings = get_settings()
reading_styles()
severity_labels = {"high": "Alta", "medium": "Média", "low": "Baixa"}
category_labels = {
    "obligation": "Obrigação documental", "deadline": "Prazo documental",
    "risk": "Possível risco", "inconsistency": "Possível inconsistência",
}

st.title("Análises")
st.caption("Obrigações, prazos, riscos e possíveis inconsistências dos documentos.")
st.divider()

try:
    documents = list_documents(settings)
except (OSError, sqlite3.Error, ValueError):
    st.error("Não foi possível consultar os documentos no banco local.")
    st.stop()

documents_by_id = {document.id: document for document in documents}
if documents:
    st.subheader("Nova análise")
    st.caption(
        f"Selecione até {MAX_ANALYSIS_DOCUMENTS} documentos. Serão usados até "
        f"{MAX_ANALYSIS_TEXT_CHARS:,} caracteres do texto disponível, distribuídos entre eles."
    )
    st.caption(
        "Demonstração: selecione os PDFs fictícios gerados pelo projeto. A análise é simulada e não usa a API."
        if settings.demo_mode else
        f"Ao analisar, os trechos são enviados ao provedor {settings.provider_label} e podem gerar custos. Resultados já salvos são reutilizados."
    )
    selected_ids = st.multiselect(
        "Documentos para análise", options=list(documents_by_id),
        format_func=lambda document_id: (
            f"{documents_by_id[document_id].original_filename} · {document_id[:8]}"
        ),
        max_selections=MAX_ANALYSIS_DOCUMENTS,
    )
    for document_id in selected_ids:
        document = documents_by_id[document_id]
        if document.processed_pages < document.total_pages:
            st.warning(f"{document.original_filename}: só {document.processed_pages} de {document.total_pages} páginas estão disponíveis.")
        if document.status == "no_text":
            st.warning(f"{document.original_filename}: sem texto extraível; selecione um PDF com texto.")
    if st.button("Analisar documentos", type="primary", disabled=not selected_ids) and selected_ids:
        with st.spinner("Analisando fatos, auditando riscos e preparando recomendações..."):
            try:
                analysis = analyze_documents(settings, selected_ids)
            except LLMError as error:
                st.error(str(error))
            except ValueError as error:
                # Mensagens de pré-validação não contêm respostas ou conteúdo do modelo.
                st.error(str(error) if settings.demo_mode else "Não foi possível analisar a seleção. Confira se os documentos existem e têm pelo menos 20 caracteres de texto extraível cada.")
            except (OSError, sqlite3.Error):
                st.error("Não foi possível salvar a análise. Confira o armazenamento local antes de tentar novamente.")
            else:
                st.session_state["selected_analysis"] = analysis.id
                st.success("Análise disponível. O resultado está salvo para consultas futuras.")

st.divider()
st.subheader("Análises salvas")
try:
    saved_analyses = list_analyses(settings)
except (OSError, sqlite3.Error, ValueError):
    st.error("Não foi possível consultar as análises salvas.")
    st.stop()

if not saved_analyses:
    st.info("Nenhuma análise disponível. Envie documentos e clique em Analisar documentos.")
else:
    saved_by_id = {item["id"]: item for item in saved_analyses}
    if st.session_state.get("selected_analysis") not in saved_by_id:
        st.session_state["selected_analysis"] = saved_analyses[0]["id"]
    analysis_id = st.selectbox(
        "Análise salva", options=list(saved_by_id), key="selected_analysis",
        format_func=lambda item_id: (
            datetime.fromisoformat(saved_by_id[item_id]["created_at"])
            .astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M (UTC-3)")
            + f" · {item_id[:8]}"
        ),
    )
    try:
        analysis = get_analysis(settings, analysis_id)
    except (OSError, sqlite3.Error, ValueError):
        st.error("Não foi possível recuperar a análise salva.")
        st.stop()
    if analysis is None:
        st.error("Análise não encontrada. Atualize a página.")
        st.stop()

    with st.container(border=True):
        st.subheader("Resumo da análise")
        if analysis.is_demo:
            st.warning("ANÁLISE SIMULADA - documentos fictícios, regras locais e nenhuma chamada à IA.")
        overview = [
            ("Documentos", len(analysis.document_ids)),
            ("Obrigações", sum(item.category == "obligation" for item in analysis.findings)),
            ("Prazos", sum(item.category == "deadline" for item in analysis.findings)),
            ("Possíveis riscos", sum(item.category in {"risk", "inconsistency"} for item in analysis.findings)),
            ("Alta prioridade", sum(item.severity == "high" and item.category in {"risk", "inconsistency"} for item in analysis.findings)),
        ]
        for column, (label, value) in zip(st.columns(5), overview):
            column.metric(label, value, help="Possíveis riscos e inconsistências de prioridade alta." if label == "Alta prioridade" else None)
        reading_text(analysis.summary)
        st.caption(f"Modelo: {analysis.model} · {len(analysis.document_ids)} documento(s)")
    st.caption(
        "Citação verificada significa que o trecho existe na página indicada. "
        "Riscos e inconsistências são hipóteses para revisão humana, sem comprovação automática de violação."
    )
    for warning in analysis.warnings:
        st.warning(warning)
    if not analysis.findings:
        st.info("Nenhum achado com evidências verificáveis nesta análise. Isso não garante ausência de riscos.")

    st.subheader("Achados e recomendações")
    reading_view = st.radio(
        "O que você quer revisar?", ["Todos", "Riscos", "Prazos", "Obrigações"], horizontal=True,
        key="analysis_reading_view",
    )
    with st.container(border=True):
        st.caption("Combine os filtros para revisar os achados. Uma seleção vazia inclui todas as opções.")
        priority_column, category_column, document_column = st.columns([1, 1, 1.5])
        with priority_column:
            priorities = st.multiselect(
                "Prioridade", options=["high", "medium", "low"],
                format_func=lambda value: severity_labels[value],
            )
        with category_column:
            categories = st.multiselect(
                "Categoria", options=list(category_labels), format_func=lambda value: category_labels[value],
            )
        with document_column:
            filter_document_id = st.selectbox(
                "Documento de referência", options=[""] + analysis.document_ids,
                format_func=lambda document_id: (
                    "Todos os documentos" if not document_id else
                    f"{documents_by_id[document_id].original_filename} · {document_id[:8]}"
                    if document_id in documents_by_id else document_id
                ),
            )
    filtered_findings = filter_analysis_findings(analysis.findings, priorities, categories, filter_document_id)
    view_categories = {"Riscos": {"risk", "inconsistency"}, "Prazos": {"deadline"}, "Obrigações": {"obligation"}}
    if reading_view in view_categories:
        filtered_findings = [item for item in filtered_findings if item.category in view_categories[reading_view]]
    st.caption(f"Exibindo {len(filtered_findings)} de {len(analysis.findings)} achado(s) desta análise.")
    if analysis.findings and not filtered_findings:
        st.info("Nenhum achado corresponde aos filtros selecionados. Ajuste ou limpe os filtros para ampliar a consulta.")
    for finding in filtered_findings:
        with st.container(border=True):
            finding_heading(finding.title, finding.severity, severity_labels[finding.severity], category_labels[finding.category])
            st.markdown("**O que foi identificado**")
            reading_text(finding.description)
            st.markdown("**Ação recomendada**")
            reading_text(finding.recommended_action, variant="action")
            references = list(dict.fromkeys(f"{item.filename} · pág. {item.page_number}" for item in finding.evidence))
            st.caption("Fontes: " + " | ".join(references))
            with st.expander(f"Ver trechos originais · {len(finding.evidence)} fonte(s)", expanded=False):
                st.caption("Correspondência literal conferida. A interpretação ainda exige revisão humana.")
                for evidence in finding.evidence:
                    st.text(f"{evidence.filename} · página {evidence.page_number}")
                    reading_text(evidence.quote, variant="source")
