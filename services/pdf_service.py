"""Leitura de texto de PDFs sem OCR e com limite de páginas."""

import pymupdf

from config import MAX_PDF_PAGES
from models.schemas import DocumentPage, ExtractedPDF


def extract_pdf_text(content: bytes) -> ExtractedPDF:
    """Abre um PDF em memória e extrai até dez páginas, fechando os recursos."""
    if not content.startswith(b"%PDF-"):
        raise ValueError("Assinatura inválida. O arquivo deve começar com %PDF-.")
    try:
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            if not pdf.is_pdf:
                raise ValueError("O arquivo enviado não é um PDF válido.")
            if pdf.needs_pass:
                raise ValueError("PDF protegido por senha. Envie uma cópia sem senha.")
            if pdf.page_count < 1:
                raise ValueError("O PDF não contém páginas para processar.")
            pages = [
                DocumentPage(
                    page_number=index + 1,
                    extracted_text=pdf.load_page(index).get_text("text", sort=True),
                )
                for index in range(min(pdf.page_count, MAX_PDF_PAGES))
            ]
            return ExtractedPDF(total_pages=pdf.page_count, pages=pages)
    except RuntimeError:
        raise ValueError("Não foi possível abrir ou ler o PDF. O arquivo pode estar inválido ou corrompido.") from None
