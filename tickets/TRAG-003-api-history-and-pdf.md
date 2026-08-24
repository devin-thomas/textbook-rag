# TRAG-003 - API, local history, and exact-page PDFs

## Goal

Expose the application API, persist conversations on Titan, and safely stream configured PDFs for exact-page viewing.

## Dependencies

TRAG-001 and TRAG-002.

## Acceptance Criteria

- Health, sources, query, conversation list/detail, delete-one, clear-all, and PDF routes match `SPEC.md`.
- Clear-all requires explicit confirmation and cannot delete source/index data.
- Query responses persist provider choice, actual provider, fallback status, citations, and ranked evidence.
- PDF serving resolves only configured source IDs, supports browser range requests, and cannot traverse paths.
- Application supports the `/textbooks` root path in development and production.
- API tests cover validation, persistence, deletion boundaries, error shapes, and PDF allowlisting/ranges.

