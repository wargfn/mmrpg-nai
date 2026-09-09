"""Local tagged retrieval index for source-material PDFs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mmrpg_nai.models.core import SourceMaterial
from mmrpg_nai.storage.store import Store

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "what",
    "when",
    "with",
}
_DOMAIN_TAGS = {
    "rules": {"rule", "rules", "check", "checks", "combat", "attack", "defense", "damage", "initiative"},
    "background": {"background", "lore", "history", "origin", "setting", "campaign", "world"},
    "character-stats": {"character", "characters", "rank", "tier", "health", "focus", "karma", "ability", "abilities", "score", "stats"},
    "equipment": {"equipment", "weapon", "armor", "armour", "gadget", "gear", "vehicle", "item"},
    "powers": {"power", "powers", "ability", "abilities", "trait", "traits"},
}


@dataclass(slots=True)
class RetrievedChunk:
    source_material_id: str
    title: str
    text: str
    categories: list[str]
    tags: list[str]
    score: float
    page_start: int | None = None
    page_end: int | None = None


def _normalise_tag(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _tokenise(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(text.lower()) if tok not in _STOPWORDS]


def _index_path(material: SourceMaterial, store: Store) -> Path:
    index_dir = store.base_dir / "source_materials"
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir / f"{Path(material.file_path).stem}-{material.id}.rag.json"


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if chunk_size <= 0:
        chunk_size = 1200
    overlap = max(0, min(overlap, chunk_size - 1)) if chunk_size > 1 else 0
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = end - overlap
    return chunks


def _build_chunk_records(
    material: SourceMaterial,
    *,
    text: str = "",
    pages: list[str] | None = None,
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    records: list[dict] = []
    base_tags = [_normalise_tag(cat) for cat in material.categories if _normalise_tag(cat)]
    title_tags = _tokenise(material.title)
    if pages:
        for page_number, page_text in enumerate(pages, start=1):
            for idx, chunk in enumerate(_chunk_text(page_text, chunk_size, overlap), start=1):
                tags = sorted(set(base_tags + title_tags + _infer_domain_tags(chunk)))
                records.append({
                    "id": f"{material.id}-p{page_number}-{idx}",
                    "text": chunk,
                    "page_start": page_number,
                    "page_end": page_number,
                    "tags": tags,
                })
    else:
        for idx, chunk in enumerate(_chunk_text(text, chunk_size, overlap), start=1):
            tags = sorted(set(base_tags + title_tags + _infer_domain_tags(chunk)))
            records.append({
                "id": f"{material.id}-{idx}",
                "text": chunk,
                "page_start": None,
                "page_end": None,
                "tags": tags,
            })
    return records


def _infer_domain_tags(text: str) -> list[str]:
    tokens = set(_tokenise(text))
    return [tag for tag, synonyms in _DOMAIN_TAGS.items() if tokens & synonyms]


def build_source_index(
    material: SourceMaterial,
    store: Store,
    *,
    chunk_size: int,
    overlap: int,
    pages: list[str] | None = None,
) -> SourceMaterial:
    if pages:
        source_text = "\n".join(page for page in pages if page.strip())
    else:
        source_text = ""
        if material.extracted_text_path.strip():
            path = Path(material.extracted_text_path)
            if path.exists() and path.is_file():
                source_text = path.read_text(encoding="utf-8", errors="replace")
    chunk_records = _build_chunk_records(
        material,
        text=source_text,
        pages=pages,
        chunk_size=chunk_size,
        overlap=overlap,
    )
    index_path = _index_path(material, store)
    payload = {
        "source_material_id": material.id,
        "title": material.title,
        "categories": material.categories,
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "chunks": chunk_records,
    }
    index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    material.rag_index_path = str(index_path)
    material.rag_chunk_count = len(chunk_records)
    store.source_materials.save(material)
    return material


def ensure_source_index(material: SourceMaterial, store: Store, *, chunk_size: int, overlap: int) -> SourceMaterial:
    path = Path(material.rag_index_path) if material.rag_index_path.strip() else None
    if path and path.exists() and path.is_file():
        return material
    return build_source_index(material, store, chunk_size=chunk_size, overlap=overlap)


def _load_index(material: SourceMaterial) -> dict | None:
    path = Path(material.rag_index_path.strip()) if material.rag_index_path.strip() else None
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _score_chunk(query: str, query_tokens: list[str], chunk: dict, categories: list[str]) -> float:
    text = str(chunk.get("text", ""))
    if not text.strip():
        return 0.0
    text_lower = text.lower()
    text_tokens = set(_tokenise(text))
    chunk_tags = {_normalise_tag(tag) for tag in chunk.get("tags", []) if _normalise_tag(tag)}
    query_tags = set(_infer_domain_tags(query)) | {_normalise_tag(cat) for cat in categories if _normalise_tag(cat)}
    token_hits = sum(1 for token in query_tokens if token in text_tokens)
    exact_bonus = 4.0 if query.strip() and query.strip().lower() in text_lower else 0.0
    tag_bonus = 3.0 * len(query_tags & chunk_tags)
    density_bonus = min(token_hits / max(len(query_tokens), 1), 1.0)
    return float(token_hits) + tag_bonus + density_bonus + exact_bonus


def retrieve_relevant_chunks(
    materials: list[SourceMaterial],
    query: str,
    *,
    top_k: int,
    categories: list[str] | None = None,
) -> list[RetrievedChunk]:
    query_tokens = _tokenise(query)
    selected_categories = [_normalise_tag(category) for category in (categories or []) if _normalise_tag(category)]
    scored: list[RetrievedChunk] = []
    for material in materials:
        index = _load_index(material)
        if not index:
            continue
        for chunk in index.get("chunks", []):
            chunk_tags = {_normalise_tag(tag) for tag in chunk.get("tags", []) if _normalise_tag(tag)}
            if selected_categories and not (set(selected_categories) & chunk_tags):
                continue
            score = _score_chunk(query, query_tokens, chunk, selected_categories)
            if score <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    source_material_id=material.id,
                    title=material.title,
                    text=str(chunk.get("text", "")).strip(),
                    categories=list(index.get("categories", material.categories)),
                    tags=list(chunk.get("tags", [])),
                    score=score,
                    page_start=chunk.get("page_start"),
                    page_end=chunk.get("page_end"),
                )
            )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[: max(top_k, 0)]


def format_retrieved_chunks(chunks: list[RetrievedChunk], *, max_chars: int) -> str:
    if not chunks or max_chars <= 0:
        return ""
    parts: list[str] = []
    remaining = max_chars
    for chunk in chunks:
        location = ""
        if chunk.page_start is not None:
            location = f" (page {chunk.page_start})" if chunk.page_start == chunk.page_end else f" (pages {chunk.page_start}-{chunk.page_end})"
        categories = f" [{', '.join(chunk.categories)}]" if chunk.categories else ""
        text = chunk.text[:remaining].strip()
        if not text:
            continue
        part = f"### {chunk.title}{location}{categories}\n{text}"
        if len(part) > remaining:
            part = part[:remaining].rstrip()
        parts.append(part)
        remaining -= len(part)
        if remaining <= 0:
            break
    return "\n\n".join(parts)
