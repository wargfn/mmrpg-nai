"""PDF ingestion: extract text from source material PDFs."""

from __future__ import annotations

from pathlib import Path

from mmrpg_nai.models.core import SourceMaterial
from mmrpg_nai.storage.store import Store


def ingest_pdf(
    file_path: str | Path,
    title: str,
    categories: list[str],
    store: Store,
    description: str = "",
) -> SourceMaterial:
    """Extract text from a PDF and register it as source material.

    The extracted text is saved alongside the PDF as ``<name>.txt`` in the
    source_materials data directory so it can be referenced in prompts.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError("PyMuPDF is required: pip install pymupdf") from exc

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    doc = fitz.open(str(path))
    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()

    full_text = "\n".join(pages)

    material = SourceMaterial(
        title=title,
        file_path=str(path),
        description=description,
        categories=categories,
        page_count=len(pages),
    )
    # Save extracted text next to the PDF reference
    text_dir = store.base_dir / "source_materials"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / f"{path.stem}-{material.id}.txt"
    text_path.write_text(full_text, encoding="utf-8")
    material.extracted_text_path = str(text_path)
    store.source_materials.save(material)
    return material


def load_source_text(material: SourceMaterial, max_chars: int = 50_000) -> str:
    """Load the extracted text of a source material (truncated to *max_chars*)."""
    extracted_text_path = material.extracted_text_path.strip()
    if not extracted_text_path:
        return ""
    p = Path(extracted_text_path)
    if not p.exists() or p.is_dir():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    return text[:max_chars]
