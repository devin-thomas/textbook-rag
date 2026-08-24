from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
from collections.abc import Callable

import numpy as np
import pdfplumber
from pypdf import PdfReader

from .catalog import Catalog, Source
from .db import Database, utc_now
from .embeddings import OllamaEmbeddingClient
from .settings import Settings


EXTRACTION_VERSION = "pdfplumber-x2-y3+pypdf-fallback-v1"
CHUNKING_VERSION = "page-paragraph-3200c-320o-v1"


@dataclass(frozen=True, slots=True)
class PageRecord:
    physical_page: int
    page_label: str
    raw_text: str
    cleaned_text: str
    extraction_method: str
    character_count: int
    alphanumeric_ratio: float
    whitespace_ratio: float
    replacement_character_count: int
    diagnostic_status: str


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    id: str
    physical_page: int
    page_label: str
    ordinal: int
    char_start: int
    char_end: int
    content: str
    content_sha256: str


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=[a-z])", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        code_like = bool(re.search(r"[{};<>]", line)) or line.startswith(("$ ", ">>> ", "# "))
        if code_like:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(line)
        else:
            current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs).strip()


def page_diagnostics(raw_text: str, cleaned_text: str) -> tuple[int, float, float, int, str]:
    count = len(cleaned_text)
    raw_length = max(len(raw_text), 1)
    alphanumeric_ratio = sum(character.isalnum() for character in raw_text) / raw_length
    whitespace_ratio = sum(character.isspace() for character in raw_text) / raw_length
    replacements = raw_text.count("\ufffd")
    if not cleaned_text:
        status = "blank"
    elif (
        count < 40
        or alphanumeric_ratio < 0.35
        or (count > 200 and whitespace_ratio < 0.02)
        or replacements > 4
    ):
        status = "suspicious"
    else:
        status = "usable"
    return count, alphanumeric_ratio, whitespace_ratio, replacements, status


def chunk_page(source_id: str, page: PageRecord, target_chars: int = 3200, overlap: int = 320) -> list[ChunkRecord]:
    if page.diagnostic_status == "blank" or not page.cleaned_text:
        return []
    text = page.cleaned_text
    boundaries = [match.end() for match in re.finditer(r"\n\n|(?<=[.!?])\s+", text)]
    chunks: list[ChunkRecord] = []
    start = 0
    ordinal = 0
    while start < len(text):
        ideal_end = min(start + target_chars, len(text))
        if ideal_end < len(text):
            candidates = [point for point in boundaries if start + target_chars // 2 <= point <= ideal_end]
            end = candidates[-1] if candidates else ideal_end
        else:
            end = len(text)
        content = text[start:end].strip()
        if content:
            digest = sha256(content.encode("utf-8")).hexdigest()
            chunk_id = f"{source_id}:p{page.physical_page}:c{ordinal}:{digest[:12]}"
            chunks.append(
                ChunkRecord(
                    id=chunk_id,
                    physical_page=page.physical_page,
                    page_label=page.page_label,
                    ordinal=ordinal,
                    char_start=start,
                    char_end=end,
                    content=content,
                    content_sha256=digest,
                )
            )
            ordinal += 1
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_pages(path: Path) -> list[PageRecord]:
    reader = PdfReader(str(path), strict=False)
    labels = reader.page_labels
    records: list[PageRecord] = []
    with pdfplumber.open(path) as document:
        for index, page in enumerate(document.pages):
            method = "pdfplumber"
            extraction_failed = False
            try:
                raw = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            except Exception:
                raw = ""
                extraction_failed = True
            if not raw.strip():
                try:
                    raw = reader.pages[index].extract_text() or ""
                    if raw.strip():
                        method = "pypdf-fallback"
                except Exception:
                    raw = ""
                    extraction_failed = True
            cleaned = normalize_text(raw)
            count, alnum, whitespace, replacements, status = page_diagnostics(raw, cleaned)
            if extraction_failed and not cleaned:
                method = "failed"
                status = "extraction_error"
            label = str(labels[index]) if index < len(labels) and labels[index] else str(index + 1)
            records.append(
                PageRecord(
                    physical_page=index + 1,
                    page_label=label,
                    raw_text=raw,
                    cleaned_text=cleaned,
                    extraction_method=method,
                    character_count=count,
                    alphanumeric_ratio=alnum,
                    whitespace_ratio=whitespace,
                    replacement_character_count=replacements,
                    diagnostic_status=status,
                )
            )
    return records


class Ingestor:
    def __init__(
        self,
        database: Database,
        catalog: Catalog,
        embeddings: OllamaEmbeddingClient,
        *,
        progress: Callable[[str], None] | None = None,
    ):
        self.database = database
        self.catalog = catalog
        self.embeddings = embeddings
        self.progress = progress

    def ingest_all(
        self,
        *,
        force: bool = False,
        batch_size: int = 16,
        source_ids: tuple[str, ...] = (),
    ) -> dict[str, object]:
        # Catalog synchronization always uses the complete allowlist. A partial
        # ingestion selects work only; it must not retire the other textbooks.
        self.database.initialize(self.catalog)
        selected_sources = (
            tuple(self.catalog.source(source_id) for source_id in dict.fromkeys(source_ids))
            if source_ids
            else self.catalog.sources
        )
        report: dict[str, object] = {
            "generated_at": utc_now(),
            "embedding_model": self.embeddings.model,
            "embedding_dimension": self.embeddings.expected_dimension,
            "sources": [],
        }
        for source in selected_sources:
            report["sources"].append(self.ingest_source(source, force=force, batch_size=batch_size))
        source_reports = report["sources"]
        report["summary"] = {
            "indexed_sources": sum(item["status"] == "indexed" for item in source_reports),
            "skipped_sources": sum(item["status"] == "skipped" for item in source_reports),
            "pages": sum(int(item.get("pages", 0)) for item in source_reports),
            "chunks": sum(int(item.get("chunks", 0)) for item in source_reports),
            "flagged_pages": sum(int(item.get("flagged_count", 0)) for item in source_reports),
        }
        return report

    def ingest_source(self, source: Source, *, force: bool = False, batch_size: int = 16) -> dict[str, object]:
        path = self.catalog.file_for(source.id)
        file_hash = _file_sha256(path)
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT file_sha256, extraction_version, chunking_version, embedding_model, "
                "embedding_dimension, status, "
                "(SELECT COUNT(*) FROM pages p WHERE p.source_id=sources.id) AS stored_pages, "
                "(SELECT COUNT(*) FROM chunks c WHERE c.source_id=sources.id) AS stored_chunks, "
                "(SELECT COUNT(*) FROM pages p WHERE p.source_id=sources.id AND p.diagnostic_status!='usable') AS flagged_pages "
                "FROM sources WHERE id = ?",
                (source.id,),
            ).fetchone()
        if (
            not force
            and existing
            and existing["status"] == "ready"
            and existing["file_sha256"] == file_hash
            and existing["extraction_version"] == EXTRACTION_VERSION
            and existing["chunking_version"] == CHUNKING_VERSION
            and existing["embedding_model"] == self.embeddings.model
            and existing["embedding_dimension"] == self.embeddings.expected_dimension
        ):
            return {
                "source_id": source.id,
                "status": "skipped",
                "reason": "index_current",
                "pages": int(existing["stored_pages"]),
                "chunks": int(existing["stored_chunks"]),
                "flagged_count": int(existing["flagged_pages"]),
            }

        if self.progress:
            self.progress(f"{source.id}: extracting pages")
        pages = extract_pages(path)
        chunks = [chunk for page in pages for chunk in chunk_page(source.id, page)]
        matrices: list[np.ndarray] = []
        for offset in range(0, len(chunks), batch_size):
            matrices.append(self.embeddings.embed([chunk.content for chunk in chunks[offset : offset + batch_size]]))
            if self.progress:
                completed = min(offset + batch_size, len(chunks))
                self.progress(f"{source.id}: embedded {completed}/{len(chunks)} chunks")
        matrix = (
            np.concatenate(matrices, axis=0)
            if matrices
            else np.empty((0, self.embeddings.expected_dimension), dtype=np.float32)
        )
        if matrix.shape != (len(chunks), self.embeddings.expected_dimension):
            raise RuntimeError("complete source embedding matrix was not produced")

        with self.database.transaction() as connection:
            connection.execute("DELETE FROM chunks_fts WHERE source_id = ?", (source.id,))
            connection.execute("DELETE FROM pages WHERE source_id = ?", (source.id,))
            page_ids: dict[int, int] = {}
            for page in pages:
                cursor = connection.execute(
                    "INSERT INTO pages(source_id, physical_page, page_label, raw_text, cleaned_text, "
                    "extraction_method, character_count, alphanumeric_ratio, whitespace_ratio, "
                    "replacement_character_count, diagnostic_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (source.id, *asdict(page).values()),
                )
                page_ids[page.physical_page] = int(cursor.lastrowid)
            for chunk, embedding in zip(chunks, matrix, strict=True):
                connection.execute(
                    "INSERT INTO chunks(id, source_id, page_id, physical_page, page_label, ordinal, "
                    "char_start, char_end, content, content_sha256, embedding, embedding_dimension) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.id,
                        source.id,
                        page_ids[chunk.physical_page],
                        chunk.physical_page,
                        chunk.page_label,
                        chunk.ordinal,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.content,
                        chunk.content_sha256,
                        embedding.astype("<f4", copy=False).tobytes(),
                        self.embeddings.expected_dimension,
                    ),
                )
                connection.execute(
                    "INSERT INTO chunks_fts(chunk_id, source_id, physical_page, content) VALUES (?, ?, ?, ?)",
                    (chunk.id, source.id, chunk.physical_page, chunk.content),
                )
            connection.execute(
                "UPDATE sources SET file_sha256=?, page_count=?, extraction_version=?, chunking_version=?, "
                "embedding_model=?, embedding_dimension=?, status='ready', indexed_at=? WHERE id=?",
                (
                    file_hash,
                    len(pages),
                    EXTRACTION_VERSION,
                    CHUNKING_VERSION,
                    self.embeddings.model,
                    self.embeddings.expected_dimension,
                    utc_now(),
                    source.id,
                ),
            )
        flagged = [page.physical_page for page in pages if page.diagnostic_status != "usable"]
        return {
            "source_id": source.id,
            "status": "indexed",
            "pages": len(pages),
            "chunks": len(chunks),
            "flagged_pages": flagged,
            "flagged_count": len(flagged),
        }

    @staticmethod
    def write_report(report: dict[str, object], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Index the configured semester textbooks")
    parser.add_argument("--force", action="store_true", help="rebuild sources even if the index is current")
    parser.add_argument("--source", action="append", dest="source_ids", help="index only this configured source ID")
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    settings = Settings.from_env()
    catalog = Catalog.load(settings.catalog_path, settings.root)
    database = Database(settings.database_path)
    embeddings = OllamaEmbeddingClient(
        settings.ollama_base_url,
        settings.embedding_model,
        settings.embedding_dimension,
    )
    ingestor = Ingestor(database, catalog, embeddings, progress=lambda message: print(message, flush=True))
    report = ingestor.ingest_all(
        force=args.force,
        batch_size=args.batch_size,
        source_ids=tuple(args.source_ids or ()),
    )
    Ingestor.write_report(report, settings.report_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
