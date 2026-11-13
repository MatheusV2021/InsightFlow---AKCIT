"""Estruturas validadas do processamento e armazenamento de documentos."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DocumentPage(BaseModel):
    """Texto extraído de uma página, com numeração iniciando em um."""

    page_number: int = Field(ge=1)
    extracted_text: str


class ExtractedPDF(BaseModel):
    """Resultado da leitura limitada de um PDF."""

    total_pages: int = Field(ge=1)
    pages: list[DocumentPage]


class Document(BaseModel):
    """Metadados persistidos de um documento processado."""

    id: str
    original_filename: str
    stored_filename: str
    uploaded_at: datetime
    total_pages: int = Field(ge=1)
    processed_pages: int = Field(ge=1)
    status: Literal["processed", "partial", "no_text"]


class UploadResult(BaseModel):
    """Resultado individual de uma operação que pode conter vários arquivos."""

    original_filename: str
    document: Document | None = None
    error: str | None = None


class Evidence(BaseModel):
    """Citação literal cuja origem deve ser conferida pelo serviço."""

    document_id: str
    filename: str
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=600)


class SourcePage(BaseModel):
    """Trecho limitado de uma página disponível para análise."""

    document_id: str
    filename: str
    page_number: int
    text: str


class ExtractedFact(BaseModel):
    """Obrigação, prazo ou fato extraído pelo analista."""

    category: Literal["obligation", "deadline", "fact"]
    description: str = Field(min_length=1, max_length=1200)
    evidence: list[Evidence] = Field(min_length=1, max_length=4)


class AnalystOutput(BaseModel):
    facts: list[ExtractedFact] = Field(max_length=20)


class FindingDraft(BaseModel):
    """Achado proposto pelo modelo, ainda sujeito à checagem de evidências."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1600)
    category: Literal["obligation", "deadline", "risk", "inconsistency"]
    severity: Literal["low", "medium", "high"]
    recommended_action: str = Field(min_length=1, max_length=1200)
    evidence: list[Evidence] = Field(min_length=1, max_length=4)


class AuditorOutput(BaseModel):
    findings: list[FindingDraft] = Field(max_length=20)


class Finding(FindingDraft):
    """Achado com identificador local e citações verificadas."""

    id: str


class Analysis(BaseModel):
    """Resultado persistido, recuperável sem novas chamadas ao modelo."""

    id: str
    created_at: datetime
    model: str
    document_ids: list[str]
    summary: str
    warnings: list[str]
    discarded_findings: int = Field(ge=0)
    findings: list[Finding]
    is_demo: bool = False


class ChatStatement(BaseModel):
    """Afirmação proposta pelo modelo com referências próprias."""

    text: str = Field(min_length=1, max_length=1600)
    evidence: list[Evidence] = Field(max_length=4)


class ChatModelOutput(BaseModel):
    """Saída estruturada; não há um resumo livre sem referências."""

    sufficient_evidence: bool
    statements: list[ChatStatement] = Field(max_length=6)


class ChatResponse(BaseModel):
    """Resposta validada para exibição e histórico de sessão."""

    answer: str
    evidence: list[Evidence]
    warnings: list[str]
    is_demo: bool = False
