"""Validação e leitura limitada de PDFs usando PyMuPDF real."""

from unittest.mock import patch

import pymupdf
import pytest

from services.pdf_service import extract_pdf_text


def test_valid_pdf_preserves_page_numbers_and_closes_resource(make_pdf):
    content = make_pdf(("First page", "Second page"))
    pdf = pymupdf.open(stream=content, filetype="pdf")
    with patch("services.pdf_service.pymupdf.open", return_value=pdf):
        result = extract_pdf_text(content)
    assert pdf.is_closed
    assert result.total_pages == 2
    assert [page.page_number for page in result.pages] == [1, 2]
    assert "First page" in result.pages[0].extracted_text
    assert "Second page" in result.pages[1].extracted_text


@pytest.mark.parametrize("content", [b"not a PDF", b"%PDF-1.7\ninvalid data", b""])
def test_invalid_pdf_is_rejected(content):
    with pytest.raises(ValueError):
        extract_pdf_text(content)


def test_pdf_without_text(make_pdf):
    result = extract_pdf_text(make_pdf(("", "")))
    assert result.total_pages == 2
    assert all(not page.extracted_text.strip() for page in result.pages)


def test_image_only_pdf_is_not_ocr_processed(make_pdf):
    with pymupdf.open(stream=make_pdf(("Visible text in an image",)), filetype="pdf") as source:
        image = source[0].get_pixmap().tobytes("png")
    with pymupdf.open() as scanned:
        page = scanned.new_page()
        page.insert_image(page.rect, stream=image)
        content = scanned.tobytes()
    result = extract_pdf_text(content)
    assert result.total_pages == 1
    assert not result.pages[0].extracted_text.strip()


def test_only_first_ten_pages_are_processed(make_pdf):
    result = extract_pdf_text(make_pdf(tuple(f"Page {number}" for number in range(1, 13))))
    assert result.total_pages == 12
    assert len(result.pages) == 10
    assert result.pages[-1].page_number == 10
    assert "Page 10" in result.pages[-1].extracted_text


def test_password_protected_pdf_is_rejected_and_closed(make_pdf):
    with pymupdf.open(stream=make_pdf(), filetype="pdf") as original:
        content = original.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-password",
            user_pw="user-password",
        )
    pdf = pymupdf.open(stream=content, filetype="pdf")
    with patch("services.pdf_service.pymupdf.open", return_value=pdf):
        with pytest.raises(ValueError, match="senha"):
            extract_pdf_text(content)
    assert pdf.is_closed
