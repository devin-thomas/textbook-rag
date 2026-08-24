from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from textbook_rag.catalog import Catalog
from textbook_rag.db import Database


class FakeEmbeddings:
    def __init__(self, vectors: dict[str, list[float]] | None = None, dimension: int = 3):
        self.expected_dimension = dimension
        self.model = "qwen3-embedding:4b"
        self.vectors = vectors or {}
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        values = [self.vectors.get(text, [1.0, 0.0, 0.0]) for text in texts]
        return np.asarray(values, dtype=np.float32)


@pytest.fixture
def catalog_factory(tmp_path: Path):
    def factory(source_count: int = 1) -> tuple[Catalog, Path]:
        sources = []
        for index in range(source_count):
            file_name = f"book-{index}.pdf"
            (tmp_path / file_name).write_bytes(b"%PDF-1.4 test pdf bytes")
            sources.append(
                {
                    "id": f"book-{index}",
                    "title": f"Book {index}",
                    "file_name": file_name,
                    "course_ids": ["COURSE-1"],
                }
            )
        catalog_path = tmp_path / "sources.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "courses": [{"id": "COURSE-1", "name": "Course One"}],
                    "sources": sources,
                }
            ),
            encoding="utf-8",
        )
        return Catalog.load(catalog_path, tmp_path), catalog_path

    return factory


@pytest.fixture
def seeded_database(tmp_path: Path, catalog_factory):
    catalog, _ = catalog_factory(2)
    database = Database(tmp_path / "test.sqlite3")
    database.initialize(catalog)
    vectors = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    contents = (
        "Virtual memory pages are loaded into physical memory after a page fault.",
        "Semantic HTML elements describe the meaning and structure of web content.",
    )
    with database.transaction() as connection:
        for index, source in enumerate(catalog.sources):
            connection.execute(
                "UPDATE sources SET status='ready', embedding_dimension=3 WHERE id=?", (source.id,)
            )
            page_id = connection.execute(
                "INSERT INTO pages(source_id, physical_page, page_label, raw_text, cleaned_text, "
                "extraction_method, character_count, alphanumeric_ratio, whitespace_ratio, "
                "replacement_character_count, diagnostic_status) VALUES (?, 4, ?, ?, ?, 'pdfplumber', ?, .8, .1, 0, 'usable')",
                (source.id, f"P-{index}", contents[index], contents[index], len(contents[index])),
            ).lastrowid
            chunk_id = f"chunk-{index}"
            connection.execute(
                "INSERT INTO chunks(id, source_id, page_id, physical_page, page_label, ordinal, char_start, "
                "char_end, content, content_sha256, embedding, embedding_dimension) "
                "VALUES (?, ?, ?, 4, ?, 0, 0, ?, ?, ?, ?, 3)",
                (
                    chunk_id,
                    source.id,
                    page_id,
                    f"P-{index}",
                    len(contents[index]),
                    contents[index],
                    f"hash-{index}",
                    np.asarray(vectors[index], dtype="<f4").tobytes(),
                ),
            )
            connection.execute(
                "INSERT INTO chunks_fts(chunk_id, source_id, physical_page, content) VALUES (?, ?, 4, ?)",
                (chunk_id, source.id, contents[index]),
            )
    return database, catalog
