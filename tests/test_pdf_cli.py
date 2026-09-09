from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mmrpg_nai.cli.main import app
from mmrpg_nai.models.core import SourceMaterial
from mmrpg_nai.pdf.rag import build_source_index
from mmrpg_nai.storage.store import Store

runner = CliRunner()


def test_pdf_search_returns_indexed_excerpt(tmp_path: Path):
    store = Store(tmp_path)
    txt = tmp_path / "rules.txt"
    txt.write_text("Melee attacks target melee defense.", encoding="utf-8")
    material = SourceMaterial(
        title="Core Rulebook",
        file_path=str(tmp_path / "core_rules.pdf"),
        extracted_text_path=str(txt),
        categories=["rules"],
    )
    store.source_materials.save(material)
    cfg = store.load_config()
    build_source_index(
        material,
        store,
        chunk_size=cfg.rules_rag_chunk_size,
        overlap=cfg.rules_rag_chunk_overlap,
    )

    result = runner.invoke(
        app,
        ["pdf", "search", "melee defense", "--data-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "Source Search" in result.output
    assert "melee defense" in result.output.lower()


def test_pdf_reindex_updates_existing_material(tmp_path: Path):
    store = Store(tmp_path)
    txt = tmp_path / "powers.txt"
    txt.write_text("Powers can modify damage and movement.", encoding="utf-8")
    material = SourceMaterial(
        title="Power Book",
        file_path=str(tmp_path / "powers.pdf"),
        extracted_text_path=str(txt),
        categories=["powers"],
    )
    store.source_materials.save(material)

    result = runner.invoke(
        app,
        ["pdf", "reindex", material.id, "--data-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    reloaded = store.source_materials.load(material.id)
    assert reloaded is not None
    assert reloaded.rag_chunk_count > 0
    assert Path(reloaded.rag_index_path).exists()
