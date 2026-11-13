"""Cenário fictício explícito e regras locais previsíveis para o hackathon."""

from models.schemas import Evidence, FindingDraft, SourcePage

DEMO_MODEL = "demo-local-v1"
SAMPLE_BANNER = "DOCUMENTO FICTÍCIO - DEMONSTRAÇÃO SEM VALIDADE JURÍDICA"
SAMPLE_FOOTER = "Material sintético para hackathon. Não representa empresas ou contratos reais."
SAMPLE_DOCUMENTS = {
    "supplier": {
        "filename": "FICTICIO_01_contrato_fornecedor.pdf", "title": "Contrato de fornecedor",
        "sections": [
            ("1. Partes e objeto", "A Horizonte Exemplo Ltda. contrata a Nuvem de Papel Fornecimentos Ltda.\nAs duas empresas são fictícias. Objeto: fornecimento de materiais de escritório."),
            ("2. Pagamento", "Pagamento: 10 dias corridos após aceite e nota fiscal válida.\nO aceite deve ser registrado pelo setor operacional."),
            ("3. Multa", "Multa: 2% sobre a parcela vencida em caso de atraso imputável à contratante.\nNão há registro de vencimento, pagamento ou atraso neste exemplo."),
            ("4. Obrigações", "O fornecedor deve entregar os itens acordados e apresentar nota fiscal válida.\nA contratante deve conferir a entrega, registrar o aceite e cumprir o prazo."),
            ("5. Contexto da exceção", "Prazo de 10 dias depende de autorização financeira escrita.\nEste material não informa se a autorização já foi concedida."),
        ],
    },
    "finance": {
        "filename": "FICTICIO_02_politica_financeira.pdf", "title": "Política financeira",
        "sections": [
            ("1. Empresa e escopo", "Política da Horizonte Exemplo Ltda., empresa fictícia.\nAplica-se às compras de materiais de escritório do contrato demonstrativo."),
            ("2. Prazo padrão", "Prazo padrão: 30 dias corridos após aceite e nota fiscal válida.\nO prazo padrão orienta o planejamento financeiro de compras."),
            ("3. Aprovação", "Aprovação financeira prévia é obrigatória antes de assumir o compromisso.\nO setor financeiro deve verificar orçamento, condições e documentação."),
            ("4. Exceções", "Prazos diferentes podem ser aprovados por escrito pelo setor financeiro.\nA exceção deve ser registrada antes do compromisso e vinculada ao contrato."),
            ("5. Interpretação", "O prazo padrão não invalida automaticamente uma exceção autorizada.\nEste exemplo não inclui o registro de aprovação do prazo de 10 dias."),
        ],
    },
    "operations": {
        "filename": "FICTICIO_03_manual_operacional.pdf", "title": "Manual operacional",
        "sections": [
            ("1. Escopo", "Manual da Horizonte Exemplo Ltda., empresa fictícia.\nOrienta as compras e o recebimento de materiais do contrato demonstrativo."),
            ("2. Aprovação prévia", "A operação deve obter aprovação financeira antes de confirmar a compra.\nO setor operacional não pode alterar prazos sem autorização financeira."),
            ("3. Responsabilidades", "O setor operacional confere a entrega e registra o aceite.\nO fornecedor deve ser avisado de divergências documentadas no recebimento."),
            ("4. Documentação", "Anexar contrato, nota fiscal, aceite e aprovação financeira ao pedido.\nExceções de prazo devem conter justificativa e autorização por escrito."),
            ("5. Contexto", "Um prazo negociado de 10 dias pode exigir um fluxo mais rápido de aprovação.\nA ausência de aprovação neste exemplo não comprova descumprimento real."),
        ],
    },
}


def sample_text_parts(kind: str) -> list[str]:
    """Conteúdo canônico compartilhado pelo gerador e pela identificação dos exemplos."""
    spec = SAMPLE_DOCUMENTS[kind]
    return [SAMPLE_BANNER, spec["title"], f"INSIGHTFLOW-DEMO-v1:{kind}",
            *[part for heading, body in spec["sections"] for part in (heading, body)],
            SAMPLE_FOOTER, "Página 1 de 1"]


def build_demo_findings(sources: list[SourcePage]) -> list[FindingDraft]:
    """Aceita somente o texto integral dos PDFs gerados; não interpreta PDFs arbitrários."""
    by_kind = {}
    for source in sources:
        kind = next((key for key in SAMPLE_DOCUMENTS if
                     " ".join(source.text.split()) == " ".join(" ".join(sample_text_parts(key)).split())), None)
        if kind is None or source.page_number != 1 or kind in by_kind:
            raise ValueError("No modo demonstração, selecione apenas uma cópia de cada PDF fictício gerado por scripts/create_sample_pdfs.py. Para outros PDFs, use DEMO_MODE=false.")
        by_kind[kind] = source

    def cite(kind: str, quote: str) -> Evidence:
        source = by_kind[kind]
        return Evidence(document_id=source.document_id, filename=source.filename,
                        page_number=source.page_number, quote=quote)

    findings = []
    if "supplier" in by_kind:
        deadline = cite("supplier", "Pagamento: 10 dias corridos após aceite e nota fiscal válida.")
        findings.extend([
            FindingDraft(title="Prazo contratual de 10 dias", category="deadline", severity="low",
                         description="O contrato fictício prevê 10 dias após aceite e nota fiscal válida; não há data de vencimento calculável neste exemplo.",
                         recommended_action="Registrar a data do aceite e da nota fiscal antes de calcular o vencimento.", evidence=[deadline]),
            FindingDraft(title="Possível exposição a multa por atraso", category="risk", severity="high",
                         description="A cláusula de multa pode gerar impacto se ocorrer atraso imputável à contratante. O exemplo não comprova atraso ou dívida vencida.",
                         recommended_action="Financeiro e operação devem conciliar o aceite, a aprovação e o prazo contratual antes do pagamento.",
                         evidence=[deadline, cite("supplier", "Multa: 2% sobre a parcela vencida em caso de atraso imputável à contratante.")]),
        ])
    if "supplier" in by_kind and "finance" in by_kind:
        findings.append(FindingDraft(
            title="Possível divergência entre prazo padrão e negociado", category="inconsistency", severity="medium",
            description="O contrato usa 10 dias e a política usa 30 dias como padrão. A política admite exceção escrita; é preciso confirmar a autorização, sem presumir violação.",
            recommended_action="Confirmar com o financeiro se a exceção de 10 dias foi autorizada e anexar o registro ao contrato.",
            evidence=[cite("supplier", "Pagamento: 10 dias corridos após aceite e nota fiscal válida."),
                      cite("finance", "Prazo padrão: 30 dias corridos após aceite e nota fiscal válida."),
                      cite("finance", "Prazos diferentes podem ser aprovados por escrito pelo setor financeiro.")],
        ))
    if "finance" in by_kind or "operations" in by_kind:
        evidence = []
        if "finance" in by_kind:
            evidence.append(cite("finance", "Aprovação financeira prévia é obrigatória antes de assumir o compromisso."))
        if "operations" in by_kind:
            evidence.append(cite("operations", "A operação deve obter aprovação financeira antes de confirmar a compra."))
        findings.append(FindingDraft(
            title="Formalizar aprovação e documentação prévias", category="obligation", severity="medium",
            description="Os procedimentos fictícios exigem aprovação financeira antes do compromisso. Não há evidência de que essa etapa tenha sido descumprida.",
            recommended_action="Operação deve reunir contrato, nota fiscal e aceite; financeiro deve documentar a aprovação e eventuais exceções.",
            evidence=evidence,
        ))
    return findings
