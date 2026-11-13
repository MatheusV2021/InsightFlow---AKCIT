"""Upload e consulta de PDFs usando apenas componentes nativos do Streamlit."""

import sqlite3
from datetime import timezone, timedelta

import streamlit as st

from config import MAX_DOCUMENTS_PER_OPERATION, MAX_FILE_SIZE_MB, MAX_PDF_PAGES, get_settings
from services.document_service import get_document, get_document_pages, list_documents, process_documents
from ui_reading import reading_styles, reading_text

settings = get_settings()
reading_styles()
status_labels = {"processed": "Processado", "partial": "Parcial", "no_text": "Sem texto extraível"}

# Localiza os textos visuais internos do seletor sem substituir o componente nativo.
st.html(f"""
<style>
[data-testid="stFileUploaderDropzone"] button p {{ font-size: 0; }}
[data-testid="stFileUploaderDropzone"] button p::after {{
    content: "Selecionar PDFs"; font-size: 0.875rem;
}}
[data-testid="stFileUploaderDropzoneInstructions"] > div {{ display: none; }}
[data-testid="stFileUploaderDropzoneInstructions"]::after {{
    content: "PDF · até {MAX_FILE_SIZE_MB} MB por arquivo"; font-size: 0.875rem;
}}
</style>
""")

st.title("Documentos")
st.caption("Organize os documentos corporativos em um só lugar.")
st.divider()

with st.container(border=True):
    st.subheader("Enviar documentos")
    st.caption(
        f"Selecione até {MAX_DOCUMENTS_PER_OPERATION} PDFs, com {MAX_FILE_SIZE_MB} MB por arquivo. "
        f"Serão lidas as primeiras {MAX_PDF_PAGES} páginas de cada documento, sem OCR."
    )
    upload_version = st.session_state.get("document_upload_version", 0)
    uploaded_files = st.file_uploader(
        "Selecione os documentos",
        type=["pdf"], accept_multiple_files=True, max_upload_size=MAX_FILE_SIZE_MB,
        key=f"document_uploads_{upload_version}",
    )
    too_many_files = len(uploaded_files) > MAX_DOCUMENTS_PER_OPERATION
    if too_many_files:
        st.error(f"Selecione no máximo {MAX_DOCUMENTS_PER_OPERATION} documentos por operação.")

    if (
        st.button("Processar documentos", disabled=not uploaded_files or too_many_files, type="primary")
        and uploaded_files and not too_many_files
    ):
        with st.spinner("Lendo PDFs e salvando os documentos..."):
            try:
                results = process_documents(
                    settings, [(file.name, file.getvalue()) for file in uploaded_files]
                )
            except ValueError as error:
                st.error(str(error))
            else:
                # A sessão guarda referências e feedback, sem cópias dos documentos persistidos.
                st.session_state["document_upload_feedback"] = [
                    {"filename": result.original_filename, "error": result.error,
                     "document_id": result.document.id if result.document is not None else None}
                    for result in results
                ]
                st.session_state["document_upload_version"] = upload_version + 1
                st.rerun()

for result in st.session_state.get("document_upload_feedback", []):
    if result["error"]:
        st.error(f"{result['filename']}: {result['error']}")
    elif result["document_id"]:
        try:
            document = get_document(settings, result["document_id"])
        except (OSError, sqlite3.Error, ValueError):
            st.error("Não foi possível consultar o resultado do envio. Confira a biblioteca abaixo.")
            continue
        if document is None:
            continue
        message = (
            f"{document.original_filename}: salvo. "
            f"{document.processed_pages} de {document.total_pages} páginas processadas."
        )
        if document.status == "no_text":
            st.warning(
                f"{message} Nenhum texto extraível nas páginas processadas. "
                "O PDF pode ser digitalizado; este MVP não realiza OCR."
            )
        else:
            st.success(message)
        if document.processed_pages < document.total_pages:
            st.warning(f"{document.original_filename}: processamento parcial, limitado às primeiras {MAX_PDF_PAGES} páginas.")

st.divider()
st.subheader("Documentos salvos")
try:
    documents = list_documents(settings)
except (OSError, sqlite3.Error):
    st.error("Não foi possível consultar os documentos no banco local.")
    st.stop()

if not documents:
    st.info("Nenhum documento cadastrado. Envie um PDF e clique em Processar documentos.")
else:
    total_column, partial_column, text_column = st.columns(3)
    total_column.metric("Documentos salvos", len(documents), border=True)
    partial_column.metric("Processamento parcial", sum(document.processed_pages < document.total_pages for document in documents), border=True)
    text_column.metric("Sem texto extraível", sum(document.status == "no_text" for document in documents), border=True)
    st.dataframe(
        [
            {
                "Documento": document.original_filename,
                "Enviado em (UTC-3)": document.uploaded_at.astimezone(
                    timezone(timedelta(hours=-3))
                ).strftime("%d/%m/%Y %H:%M:%S"),
                "Páginas totais": document.total_pages,
                "Páginas processadas": document.processed_pages,
                "Status": status_labels[document.status],
                "Processamento parcial": "Sim" if document.processed_pages < document.total_pages else "Não",
            }
            for document in documents
        ],
        hide_index=True,
        width="stretch",
    )
    st.subheader("Visualizar texto extraído")
    documents_by_id = {document.id: document for document in documents}
    selected_id = st.selectbox(
        "Documento salvo",
        options=list(documents_by_id),
        format_func=lambda document_id: (
            f"{documents_by_id[document_id].original_filename} · {document_id[:8]}"
        ),
    )
    selected_document = documents_by_id[selected_id]
    st.caption(
        f"{selected_document.original_filename} · {status_labels[selected_document.status]} · "
        f"{selected_document.processed_pages} de {selected_document.total_pages} páginas processadas"
    )
    if selected_document.processed_pages < selected_document.total_pages:
        st.warning(
            f"Processamento parcial: {selected_document.processed_pages} de "
            f"{selected_document.total_pages} páginas. As demais páginas não foram lidas."
        )
    if selected_document.status == "no_text":
        st.warning("Nenhum texto extraível nas páginas processadas. PDFs digitalizados precisam de OCR, indisponível neste MVP.")
    try:
        pages = get_document_pages(settings, selected_id)
    except (OSError, sqlite3.Error):
        st.error("Não foi possível recuperar o texto salvo no banco local.")
        st.stop()
    st.caption("Texto original extraído do PDF, sem interpretação da IA. As quebras de linha da extração são preservadas.")
    if pages:
        pages_by_number = {page.page_number: page for page in pages}
        page_number = st.selectbox(
            "Página para leitura", options=list(pages_by_number),
            format_func=lambda number: f"Página {number}", key=f"reading_page_{selected_id}",
        )
        with st.container(border=True):
            st.subheader(f"Página {page_number}")
            page = pages_by_number[page_number]
            if page.extracted_text.strip():
                reading_text(page.extracted_text, variant="source")
            else:
                st.caption("Esta página não contém texto extraível.")
