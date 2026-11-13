"""Gera três PDFs fictícios com PyMuPDF, sem importar dados na aplicação."""

import argparse
import sys
from pathlib import Path

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.demo_service import SAMPLE_BANNER, SAMPLE_DOCUMENTS, SAMPLE_FOOTER


def create_sample_pdfs(output_dir: Path) -> list[Path]:
    """Cria PDFs A4 identificados como fictícios, com texto selecionável."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for kind, spec in SAMPLE_DOCUMENTS.items():
        path = output_dir / spec["filename"]
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=595, height=842)
            page.draw_rect(pymupdf.Rect(0, 0, 595, 60), color=None, fill=(0.12, 0.29, 0.37))
            page.insert_text((40, 35), SAMPLE_BANNER, fontname="hebo", fontsize=10, color=(1, 1, 1))
            page.insert_text((40, 100), spec["title"], fontname="hebo", fontsize=23, color=(0.1, 0.17, 0.25))
            page.insert_text((40, 122), f"INSIGHTFLOW-DEMO-v1:{kind}", fontsize=9, color=(0.35, 0.4, 0.45))
            y = 165
            for heading, body in spec["sections"]:
                page.insert_text((40, y), heading, fontname="hebo", fontsize=12, color=(0.12, 0.29, 0.37))
                available = page.insert_textbox(pymupdf.Rect(40, y + 12, 555, y + 90), body, fontsize=11, lineheight=1.4)
                if available < 0:
                    raise ValueError("O texto de demonstração não coube na página.")
                y += 108
            page.insert_text((40, 772), SAMPLE_FOOTER, fontsize=9, color=(0.35, 0.4, 0.45))
            page.insert_text((40, 797), "Página 1 de 1", fontsize=9, color=(0.35, 0.4, 0.45))
            pdf.set_metadata({"title": spec["title"], "author": "InsightFlow AI - material fictício",
                              "subject": "Demonstração sintética sem validade jurídica"})
            pdf.save(path)
        paths.append(path)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera PDFs fictícios para demonstração do InsightFlow AI.")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "pdf")
    args = parser.parse_args()
    try:
        for generated_path in create_sample_pdfs(args.output_dir):
            print(f"PDF fictício gerado: {generated_path}")
    except (OSError, RuntimeError, ValueError):
        parser.exit(1, "Não foi possível gerar os PDFs. Confira as permissões e o espaço disponível.\n")
