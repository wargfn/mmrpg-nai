from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from mmrpg_nai.models.core import SourceMaterial
from mmrpg_nai.pdf.ingestion import ingest_pdf, load_source_text
from mmrpg_nai.pdf.rag import retrieve_relevant_chunks
from mmrpg_nai.storage.store import Store


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self) -> str:
        return self._text


class _FakeDoc:
    def __iter__(self):
        return iter([_FakePage("Page one"), _FakePage("Page two")])

    def close(self) -> None:
        return None


def test_ingest_pdf_uses_unique_extracted_text_filename(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    pdf_path = tmp_path / "core_rules.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda _: _FakeDoc()))

    first = ingest_pdf(pdf_path, "Core Rules", ["rules"], store)
    second = ingest_pdf(pdf_path, "Core Rules v2", ["rules"], store)

    assert first.extracted_text_path != second.extracted_text_path
    assert Path(first.extracted_text_path).exists()
    assert Path(second.extracted_text_path).exists()
    assert Path(first.rag_index_path).exists()
    assert Path(second.rag_index_path).exists()
    assert first.rag_chunk_count > 0
    assert second.rag_chunk_count > 0


def test_retrieve_relevant_chunks_prefers_matching_rules_text(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    pdf_path = tmp_path / "core_rules.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    class _RulesDoc:
        def __iter__(self):
            return iter([
                _FakePage("Melee attacks target the target's melee defense score."),
                _FakePage("Equipment entries list armor, weapons, and gadgets."),
            ])

        def close(self) -> None:
            return None

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda _: _RulesDoc()))
    material = ingest_pdf(pdf_path, "Core Rules", ["rules", "equipment"], store)

    chunks = retrieve_relevant_chunks([material], "How does melee defense work?", top_k=2)

    assert chunks
    assert "melee defense" in chunks[0].text.lower()


def test_load_source_text_empty_path_returns_empty():
    material = SourceMaterial(title="Rules", file_path="/fake.pdf", extracted_text_path="")
    assert load_source_text(material) == ""


def test_load_source_text_directory_path_returns_empty(tmp_path: Path):
    material = SourceMaterial(title="Rules", file_path="/fake.pdf", extracted_text_path=str(tmp_path))
    assert load_source_text(material) == ""
