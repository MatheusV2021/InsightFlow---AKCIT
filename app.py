"""Ponto de entrada e navegação da apresentação Streamlit."""

import sqlite3

import streamlit as st
from pydantic import ValidationError

from config import get_settings
from services.document_service import initialize_workspace

st.set_page_config(
    page_title="InsightFlow AI",
    page_icon=":material/insights:",
    layout="wide",
    initial_sidebar_state="auto",
)

try:
    settings = get_settings()
    initialize_workspace(settings)
except ValidationError:
    st.error("Configuração inválida. Confira AI_PROVIDER, os modelos, limites e DEMO_MODE no ambiente ou .env.")
    st.stop()
except (OSError, sqlite3.Error):
    st.error(
        "Não foi possível inicializar os dados locais. "
        "Confira o espaço e as permissões das pastas database e uploads."
    )
    st.stop()

with st.sidebar:
    st.title("InsightFlow AI")
    st.caption("Inteligência para decisões empresariais")
    st.divider()
    st.caption("VISÃO EMPRESARIAL")
    st.caption("Dados do armazenamento local")
    if settings.demo_mode:
        st.caption("DEMONSTRAÇÃO · análises simuladas · API bloqueada")
    else:
        st.caption(f"MODO NORMAL · {settings.provider_label}")
    st.caption("Documentos → Análises → Dashboard")

page = st.navigation(
    [
        st.Page("pages/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True),
        st.Page("pages/documents.py", title="Documentos", icon=":material/description:", url_path="documents"),
        st.Page("pages/analyses.py", title="Análises", icon=":material/analytics:", url_path="analyses"),
        st.Page("pages/assistant.py", title="Assistente IA", icon=":material/chat:", url_path="assistant"),
    ],
    position="sidebar",
)
st.markdown("### InsightFlow AI")
st.caption("Inteligência documental para acompanhar obrigações, priorizar riscos e orientar decisões.")
if settings.demo_mode:
    st.warning("MODO DEMONSTRAÇÃO: análises simuladas sobre PDFs fictícios e chat extrativo local. Nenhuma chamada à API. Gere os exemplos com python scripts/create_sample_pdfs.py.")
page.run()
