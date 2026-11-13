"""Conversa de sessão com perguntas explícitas e fontes documentais verificadas."""

import sqlite3

import streamlit as st

from config import MAX_CHAT_CONTEXT_CHARS, MAX_CHAT_QUESTION_CHARS, get_settings
from models.schemas import ChatResponse
from services.chat_service import ask_question, revalidate_response_sources
from services.document_service import list_documents
from services.llm_service import LLMError


def render_message(message: dict) -> None:
    """Mostra mensagens e citações como texto, sem executar conteúdo dos PDFs."""
    with st.chat_message("Você" if message["role"] == "user" else "InsightFlow AI",
                         avatar=":material/person:" if message["role"] == "user" else ":material/auto_awesome:"):
        if message["role"] == "user":
            st.text(message["content"])
            return
        if message.get("error"):
            st.error(message["error"])
            return
        try:
            response = revalidate_response_sources(settings, ChatResponse.model_validate(message["response"]))
        except (OSError, sqlite3.Error, ValueError):
            st.error("Não foi possível conferir as fontes desta resposta no banco local.")
            return
        st.text(response.answer)
        if response.is_demo:
            st.caption("Consulta demonstrativa local, sem geração por IA.")
        for warning in response.warnings:
            st.caption(warning)
        if response.evidence:
            with st.expander(f"Fontes verificadas ({len(response.evidence)})"):
                for index, evidence in enumerate(response.evidence, start=1):
                    st.caption(f"[{index}] {evidence.filename} · página {evidence.page_number} · documento {evidence.document_id}")
                    st.text(evidence.quote)


settings = get_settings()
st.title("Assistente IA")
st.caption("Faça perguntas sobre seus documentos e confira os trechos usados na resposta.")
st.divider()

try:
    documents = list_documents(settings)
except (OSError, sqlite3.Error, ValueError):
    st.error("Não foi possível consultar os documentos no banco local.")
    st.stop()

with st.expander("Perguntas sugeridas"):
    st.caption("Copie uma pergunta e adapte os termos ao conteúdo dos seus PDFs. Nenhuma sugestão é enviada automaticamente.")
    st.markdown("- Quais contratos possuem prazos de pagamento?\n- Quais obrigações de confidencialidade são mencionadas?\n- Qual é o prazo de entrega previsto nos documentos?")

documents_by_id = {document.id: document for document in documents}
selected_ids = st.multiselect(
    "Documentos para consultar", options=list(documents_by_id),
    format_func=lambda document_id: f"{documents_by_id[document_id].original_filename} · {document_id[:8]}",
    key="assistant_documents",
)
st.caption(
    f"A busca lexical seleciona até {MAX_CHAT_CONTEXT_CHARS:,} caracteres. "
    "As respostas se limitam aos trechos recuperados, sem garantir uma leitura integral. "
    "Faça perguntas completas: mensagens anteriores não são enviadas ao modelo."
)
st.caption(
    "Demonstração: serão mostrados trechos recuperados localmente, sem chamar a IA."
    if settings.demo_mode else
    "Ao enviar perguntas com trechos relevantes, a OpenAI pode gerar custos. Citações são conferidas, mas a interpretação exige revisão humana."
)
if not documents:
    st.info("Envie e processe PDFs na página Documentos para começar a conversar.")
elif not selected_ids:
    st.info("Selecione os documentos acima e envie uma pergunta para começar.")

messages = st.session_state.setdefault("assistant_messages_demo" if settings.demo_mode else "assistant_messages_real", [])
for message in messages:
    render_message(message)

question = st.chat_input(
    "Pergunte sobre os documentos selecionados...", key="assistant_question",
    max_chars=MAX_CHAT_QUESTION_CHARS, disabled=not selected_ids,
)
if question and selected_ids:
    user_message = {"role": "user", "content": question}
    messages.append(user_message)
    render_message(user_message)
    with st.spinner("Buscando trechos e preparando uma resposta fundamentada..."):
        try:
            response = ask_question(settings, question, selected_ids)
        except (LLMError, ValueError) as error:
            assistant_message = {"role": "assistant", "error": str(error)}
        except (OSError, sqlite3.Error):
            assistant_message = {"role": "assistant", "error": "Não foi possível recuperar o texto dos documentos. Confira o armazenamento local."}
        else:
            assistant_message = {"role": "assistant", "response": response.model_dump(mode="json")}
    messages.append(assistant_message)
    render_message(assistant_message)
