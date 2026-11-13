"""Componentes de leitura que preservam o conteúdo literal dos documentos."""

from html import escape

import streamlit as st


def reading_styles() -> None:
    st.html("""
    <style>
    .if-reading {font-size:1.02rem; line-height:1.8; color:#172B40;
        white-space:pre-wrap; overflow-wrap:anywhere; max-width:78ch;}
    .if-source {background:#F5F7FA; border-left:3px solid #245D70;
        border-radius:0 8px 8px 0; padding:18px 22px; margin:8px 0 16px;}
    .if-action {background:#EDF5F6; border-radius:8px; padding:16px 20px;}
    .if-heading {font-size:1.3rem; line-height:1.4; font-weight:650;
        color:#172B40; margin:10px 0 18px; overflow-wrap:anywhere;}
    .if-tags {display:flex; flex-wrap:wrap; gap:8px; margin:4px 0 8px;}
    .if-tag {font-size:.82rem; font-weight:600; border-radius:6px;
        padding:4px 10px; background:#EEF2F6; color:#374B60;}
    .if-high {background:#FBEAEA; color:#8C3030;}
    .if-medium {background:#FFF3DC; color:#805B15;}
    .if-low {background:#E9F4EF; color:#28624C;}
    </style>
    """)


def reading_text(text: str, *, variant: str = "") -> None:
    # Escape antes de inserir em HTML: PDFs e respostas do modelo são dados.
    css_class = {"source": "if-source", "action": "if-action"}.get(variant, "")
    st.html(f'<div class="if-reading {css_class}">{escape(text)}</div>')


def finding_heading(title: str, priority: str, priority_label: str, category: str) -> None:
    priority_class = {"high": "if-high", "medium": "if-medium", "low": "if-low"}[priority]
    st.html(
        f'<div class="if-tags"><span class="if-tag {priority_class}">'
        f'Prioridade {escape(priority_label.lower())}</span>'
        f'<span class="if-tag">{escape(category)}</span></div>'
        f'<h3 class="if-heading">{escape(title)}</h3>'
    )
