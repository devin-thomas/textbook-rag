from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import httpx
import pytest

from textbook_rag.catalog import Catalog, CatalogError
from textbook_rag.db import Database
from textbook_rag.embeddings import EmbeddingError, OllamaEmbeddingClient
from textbook_rag.ingest import (
    CHUNKING_VERSION,
    EXTRACTION_VERSION,
    Ingestor,
    PageRecord,
    chunk_page,
    normalize_text,
    extract_pages,
)


def test_normalize_text_dehyphenates_wrapped_prose_and_preserves_code_lines() -> None:
    text = "A virtual mem-\nory paragraph wraps\nhere.\n\nconst x = <node>;\n"
    assert normalize_text(text) == "A virtual memory paragraph wraps here.\n\nconst x = <node>;"


def test_chunks_preserve_physical_page_and_separate_label() -> None:
    page = PageRecord(12, "7", "raw", "Sentence one. " * 800, "pdfplumber", 1000, .8, .1, 0, "usable")
    chunks = chunk_page("source", page, target_chars=300, overlap=30)
    assert len(chunks) > 2
    assert {chunk.physical_page for chunk in chunks} == {12}
    assert {chunk.page_label for chunk in chunks} == {"7"}
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_catalog_rejects_file_path_traversal(tmp_path: Path) -> None:
    catalog_path = tmp_path / "sources.json"
    catalog_path.write_text(
        json.dumps(
            {
                "courses": [{"id": "C", "name": "Course"}],
                "sources": [
                    {"id": "bad", "title": "Bad", "file_name": "../secret.pdf", "course_ids": ["C"]}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError):
        Catalog.load(catalog_path, tmp_path)


def test_embedding_dimension_mismatch_fails() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"embeddings": [[1.0, 2.0]]})
    )
    client = OllamaEmbeddingClient(
        "http://ollama", "qwen3-embedding:4b", 3, client=httpx.Client(transport=transport)
    )
    with pytest.raises(EmbeddingError, match="dimension mismatch"):
        client.embed(["question"])


def test_ingestion_is_idempotent_when_index_fingerprint_matches(tmp_path: Path, catalog_factory) -> None:
    catalog, _ = catalog_factory()
    database = Database(tmp_path / "index.sqlite3")
    database.initialize(catalog)
    source = catalog.sources[0]
    file_hash = sha256(catalog.file_for(source.id).read_bytes()).hexdigest()
    with database.transaction() as connection:
        connection.execute(
            "UPDATE sources SET file_sha256=?, extraction_version=?, chunking_version=?, embedding_model=?, "
            "embedding_dimension=3, status='ready' WHERE id=?",
            (file_hash, EXTRACTION_VERSION, CHUNKING_VERSION, "qwen3-embedding:4b", source.id),
        )

    class NoCallEmbeddings:
        model = "qwen3-embedding:4b"
        expected_dimension = 3

        def embed(self, _texts):
            raise AssertionError("current source must not be embedded again")

    report = Ingestor(database, catalog, NoCallEmbeddings()).ingest_source(source)
    assert report == {
        "source_id": source.id,
        "status": "skipped",
        "reason": "index_current",
        "pages": 0,
        "chunks": 0,
        "flagged_count": 0,
    }


def test_partial_ingestion_keeps_unselected_configured_sources_ready(
    tmp_path: Path, catalog_factory
) -> None:
    catalog, _ = catalog_factory(2)
    database = Database(tmp_path / "index.sqlite3")
    database.initialize(catalog)
    with database.transaction() as connection:
        for source in catalog.sources:
            file_hash = sha256(catalog.file_for(source.id).read_bytes()).hexdigest()
            connection.execute(
                "UPDATE sources SET file_sha256=?, extraction_version=?, chunking_version=?, "
                "embedding_model=?, embedding_dimension=3, status='ready' WHERE id=?",
                (
                    file_hash,
                    EXTRACTION_VERSION,
                    CHUNKING_VERSION,
                    "qwen3-embedding:4b",
                    source.id,
                ),
            )

    class NoCallEmbeddings:
        model = "qwen3-embedding:4b"
        expected_dimension = 3

        def embed(self, _texts):
            raise AssertionError("current source must not be embedded again")

    report = Ingestor(database, catalog, NoCallEmbeddings()).ingest_all(
        source_ids=("book-0",)
    )

    assert [item["source_id"] for item in report["sources"]] == ["book-0"]
    with database.connect() as connection:
        statuses = dict(connection.execute("SELECT id, status FROM sources").fetchall())
    assert statuses == {"book-0": "ready", "book-1": "ready"}


def test_extraction_failure_is_distinct_from_a_blank_page(tmp_path: Path, monkeypatch) -> None:
    class BrokenPage:
        def extract_text(self, **_kwargs):
            raise RuntimeError("broken text layer")

    class FakePdfPlumberDocument:
        pages = [BrokenPage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class FakeReader:
        page_labels = ["1"]
        pages = [BrokenPage()]

        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr("textbook_rag.ingest.pdfplumber.open", lambda _path: FakePdfPlumberDocument())
    monkeypatch.setattr("textbook_rag.ingest.PdfReader", FakeReader)

    page = extract_pages(tmp_path / "broken.pdf")[0]

    assert page.diagnostic_status == "extraction_error"
    assert page.extraction_method == "failed"
