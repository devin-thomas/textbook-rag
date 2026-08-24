# TRAG-001 - Foundation and page-aware ingestion

## Goal

Create the repository foundation, source catalog, SQLite schema, extraction pipeline, chunking, local embedding client, and ingestion report for the four approved PDFs.

## Dependencies

None.

## Acceptance Criteria

- Python backend uses an isolated 3.12 environment and has deterministic dependency metadata.
- `config/sources.json` maps all four configured PDFs to stable source/course IDs.
- Schema migrations create source, course, page, chunk, FTS, conversation, message, and evidence tables.
- Ingestion never crosses PDF page boundaries and preserves one-based page provenance.
- `pdfplumber` uses the audited tolerance settings, `pypdf` supplies labels/fallback, and diagnostics distinguish blank pages from extraction defects.
- Physical page indices and citation page labels are stored separately and tested with known shifted-label pages.
- Embeddings come only from `qwen3-embedding:4b`; unexpected dimensions fail the run.
- Re-ingestion is idempotent and reports indexed/skipped/flagged totals per source.
- Unit tests cover normalization, chunk provenance, catalog allowlisting, idempotence, and embedding dimension validation.
