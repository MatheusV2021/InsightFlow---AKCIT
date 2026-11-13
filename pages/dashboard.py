"""Visão empresarial do histórico real de documentos e análises."""

import sqlite3
from datetime import timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from config import get_settings
from services.dashboard_service import get_dashboard_data


def build_bar_chart(labels: list[str], values: list[int], colors: list[str]) -> go.Figure:
    """Cria uma visualização acessível com valores inteiros e cores consistentes."""
    figure = go.Figure(go.Bar(
        x=labels, y=values, marker_color=colors, text=values, textposition="outside",
        hovertemplate="%{x}: %{y} risco(s)<extra></extra>",
    ))
    figure.update_layout(
        height=300, margin=dict(l=16, r=16, t=32, b=16),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#172B40"), showlegend=False, bargap=0.45,
    )
    figure.update_xaxes(title_text=None, fixedrange=True)
    figure.update_yaxes(
        title_text="Riscos", tickformat="d", dtick=1 if max(values, default=0) < 6 else None,
        rangemode="tozero", range=[0, max(1, max(values, default=0) * 1.25)],
        fixedrange=True, gridcolor="#E6EBF0",
    )
    return figure


st.title("Dashboard")
st.caption("Visão executiva dos documentos e dos pontos que merecem atenção.")
st.divider()

try:
    settings = get_settings()
    data = get_dashboard_data(settings)
except (OSError, sqlite3.Error, ValueError):
    st.error("Não foi possível carregar os indicadores. Confira o armazenamento local e tente novamente.")
    st.stop()

metrics = [
    ("Documentos cadastrados", data["document_count"], "Todos os PDFs salvos na biblioteca."),
    ("Análises realizadas", data["analysis_count"], "Resultados completos salvos no histórico."),
    ("Riscos identificados", data["risk_count"], "Possíveis riscos e inconsistências com citações conferidas."),
    ("Riscos de alta prioridade", data["high_priority_count"], "Riscos e inconsistências classificados com prioridade alta."),
]
for column, (label, value, help_text) in zip(st.columns(4), metrics):
    with column:
        st.metric(label, value, help=help_text, border=True)
st.caption(
    ("Origem: análises SIMULADAS do SQLite local. " if settings.demo_mode else "Origem: análises reais do SQLite local. ") +
    "Documentos cadastrados inclui a biblioteca compartilhada entre modos. Cada achado é contado uma vez por análise, "
    "mesmo quando cita vários documentos. A mesma questão pode aparecer em análises diferentes."
)

if not data["analysis_count"]:
    st.info("Seu dashboard começa com os documentos. Envie PDFs em Documentos e execute uma análise na página Análises para visualizar riscos e recomendações.")
    left, right = st.columns(2)
    with left:
        st.page_link("pages/documents.py", label="Enviar documentos", icon=":material/upload_file:")
    with right:
        st.page_link("pages/analyses.py", label="Ir para Análises", icon=":material/analytics:")
    st.stop()

st.caption("Riscos são hipóteses para revisão humana. Citações verificadas não comprovam descumprimento contratual.")
priority_column, category_column = st.columns(2)
with priority_column:
    with st.container(border=True):
        st.subheader("Riscos por prioridade")
        st.plotly_chart(build_bar_chart(
            ["Alta", "Média", "Baixa"], list(data["risks_by_priority"].values()),
            ["#A14B4B", "#B58A42", "#4B817A"],
        ), width="stretch", config={"displayModeBar": False}, key="risks_by_priority")
with category_column:
    with st.container(border=True):
        st.subheader("Riscos por categoria")
        st.plotly_chart(build_bar_chart(
            ["Possível risco", "Possível inconsistência"], list(data["risks_by_category"].values()),
            ["#315F7D", "#82718F"],
        ), width="stretch", config={"displayModeBar": False}, key="risks_by_category")

if not data["risk_count"]:
    st.info("Nenhum risco com evidências verificáveis nas análises salvas. Isso não garante ausência de riscos.")

alerts_column, actions_column = st.columns(2)
with alerts_column:
    with st.container(border=True):
        st.subheader("Alertas")
        if data["high_priority_alerts"]:
            st.caption("Até cinco riscos de prioridade alta, com os mais recentes primeiro.")
            for item in data["high_priority_alerts"]:
                st.warning(item["finding"].title)
                st.caption(f"Análise {item['analysis_id']} · prioridade alta")
        else:
            st.caption("Nenhum alerta de risco de alta prioridade no histórico verificado.")
        if data["partial_document_count"]:
            st.caption(f"Atenção à cobertura: {data['partial_document_count']} documento(s) com páginas não processadas.")
        if data["no_text_document_count"]:
            st.caption(f"Sem texto extraível: {data['no_text_document_count']} documento(s). O MVP não realiza OCR.")
        if data["limited_analysis_count"]:
            st.caption(f"{data['limited_analysis_count']} análise(s) com avisos de cobertura ou validação. Consulte os detalhes em Análises.")
with actions_column:
    with st.container(border=True):
        st.subheader("Recomendações em destaque")
        st.caption("Até cinco ações, ordenadas pela prioridade do risco e pela análise mais recente.")
        if not data["recommendations"]:
            st.caption("Não há recomendações associadas a riscos com citações verificadas.")
        priority_labels = {"high": "Alta", "medium": "Média", "low": "Baixa"}
        for item in data["recommendations"]:
            finding = item["finding"]
            st.markdown(f"**{finding.title}**")
            st.write(finding.recommended_action)
            st.caption(f"Prioridade {priority_labels[finding.severity].lower()} · análise {item['analysis_id']}")

with st.container(border=True):
    st.subheader("Últimas análises")
    st.dataframe([
        {
            "Data (UTC-3)": item["created_at"].astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M"),
            "Achados": item["finding_count"], "Riscos": item["risk_count"],
            "Alta prioridade": item["high_priority_count"], "Modelo": item["model"], "Análise": item["id"],
        }
        for item in data["recent_analyses"]
    ], hide_index=True, width="stretch")
    st.page_link("pages/analyses.py", label="Consultar análises e evidências", icon=":material/arrow_forward:")
