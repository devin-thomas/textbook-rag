# Textbook Desk Specification

## 1. Outcome

Textbook Desk is a private, responsive study application that answers questions from exactly four locally owned semester textbooks. It runs on `titan`, is mounted at `/textbooks` through Tailscale Serve, and uses local page-aware retrieval before generation by either NVIDIA or Ollama.

The first release succeeds when the user can ask from desktop or phone, select `Auto`, `NVIDIA`, or `Ollama`, receive a concise textbook-grounded answer with exact-page citations, inspect retrieved passages, open the original PDF at the cited page, revisit or delete local history, and continue using the existing Tailscale Serve root application.

## 2. Scope

### Included

- Index the four PDFs already present in the workspace and no other content.
- Preserve original source identity and one-based PDF page coordinates.
- Course and source filtering, including one source shared by multiple courses.
- Hybrid local retrieval using semantic embeddings and SQLite FTS.
- `Auto`, `NVIDIA`, and `Ollama` generation choices per query.
- Strict textbook-only answers with explicit abstention.
- Local conversation persistence and individual/bulk deletion.
- Responsive desktop and phone interfaces.
- In-app exact-page PDF viewing.
- Loopback-only runtime, auto-start, SSH tunnel, and Tailscale Serve path mounting.

### Excluded

- LMS imports, notes, slides, assignments, web search, public sharing, multi-user accounts, hosted storage, OCR of arbitrary future uploads, and detailed tutor mode.

## 3. Source Catalog

Source configuration lives in `config/sources.json`. Each source has a stable slug, display title, file name, page count after inspection, and one or more course IDs.

| Source slug | Display title | Courses |
| --- | --- | --- |
| `parallel-operating-systems` | Guide to Parallel Operating Systems | ITSC 1305 |
| `comptia-tech-plus` | CompTIA Tech+ Study Guide | ITSC 1305 |
| `missing-link-web` | The Missing Link | ITSE 1311, ITSE 2302 |
| `clean-coder` | The Clean Coder | INEW 2330 |

PDF file names stay out of user-facing copy. The server resolves configured file names only; request paths never select arbitrary local files.

## 4. Architecture

### Titan

- FastAPI application bound to `127.0.0.1:8766`.
- React/Vite/TypeScript frontend built with base path `/textbooks/` and served by FastAPI.
- SQLite database at `data/textbook-desk.sqlite3` for source metadata, page text, chunks, FTS, conversations, and messages.
- Float32 embeddings stored with chunk records and loaded into a NumPy matrix for this four-book corpus. Retrieval uses cosine similarity without a separate vector database.
- Original PDFs remain in the workspace and are streamed only through source IDs from the catalog.
- SSH local forward `127.0.0.1:11435 -> research:127.0.0.1:11434` supplies Ollama generation and embeddings.

### Research

- Ollama model `qwen3-embedding:4b` creates every document and query embedding.
- Ollama model `qwen3.5:9b` handles explicit Ollama generation and Auto fallback.

### NVIDIA

- OpenAI-compatible endpoint `https://integrate.api.nvidia.com/v1`.
- Default model `nvidia/nemotron-3-super-120b-a12b`, overrideable by environment.
- The API key is read server-side from `NVIDIA_API_KEY` or the existing ignored NVIDIA dotenv file; it is never copied into source control or sent to the browser.

## 5. Ingestion

1. Load only catalogued PDFs.
2. Extract each page independently with `pdfplumber 0.11.9` using `x_tolerance=2` and `y_tolerance=3`; use `pypdf 6.10.0` in non-strict mode for metadata, page labels, and per-page fallback. No chunk crosses an original page boundary.
3. Normalize Unicode, dehyphenate only line-break hyphens, join wrapped prose lines, and preserve code-like lines and paragraph breaks.
4. Record page extraction diagnostics: character count, alphanumeric ratio, whitespace ratio, replacement-character count, and extraction method.
5. Flag empty or suspicious pages; do not silently index them as good content.
6. Store the one-based physical page separately from the PDF/book page label. Split usable pages on paragraph/sentence boundaries into approximately 700-900 token chunks with limited overlap. Retain both page coordinates, source, course, ordinal, character offsets, and content hash.
7. Batch document embeddings through Ollama. The expected embedding width is 2,560; reject mixed or unexpected dimensions.
8. Upsert source/page/chunk records transactionally, rebuild FTS rows, and replace embeddings only after a complete source succeeds.
9. Write a machine-readable ingestion report with totals and flagged pages per source. Skip blank/image-only pages for v1 and do not apply blanket OCR.

Re-running ingestion is idempotent by source file hash, extraction version, chunking version, and embedding model. A model or chunking change requires a rebuild rather than mixing index versions.

## 6. Retrieval

- Apply course/source filters before ranking.
- Retrieve semantic and FTS candidates independently, then combine them with Reciprocal Rank Fusion.
- Use tunable initial candidate pools and final context count through configuration; default to 24 semantic candidates, 24 FTS candidates, and at most 8 final chunks.
- Prefer evidence diversity while allowing adjacent passages on the same page when both materially support the question.
- Return retrieval scores and exact excerpts to the UI for inspection, but never imply a score is certainty.
- If no candidate clears the evaluated support threshold, return `insufficient_evidence` without calling a generation provider.

The evaluation suite owns the threshold. The value is configuration and may be tightened after testing; provider choice never changes the embedding space or ranking behavior.

## 7. Grounded Generation

The generation prompt contains only the question, selected scope, numbered retrieved chunks, and rules. It instructs the model to:

- answer only from supplied excerpts;
- remain concise unless the question requires steps;
- cite supporting chunk IDs for each factual claim;
- state that the textbooks do not contain enough information when support is absent;
- never invent a title, page, quotation, or citation.

The server validates cited chunk IDs against the retrieved set and maps them to source/page citations. Invalid citations fail the grounded response instead of being displayed.

### Provider semantics

- `NVIDIA`: call NVIDIA once; expose provider errors; never switch.
- `Ollama`: call Ollama once; expose provider errors; never switch.
- `Auto`: call NVIDIA first. Fall back to Ollama only for connection, authentication, rate-limit, timeout, malformed-provider-response, or provider-5xx failures.
- Insufficient retrieval evidence or a valid provider abstention is not a provider failure and does not trigger fallback.
- Every successful answer records and displays the provider actually used and whether fallback occurred.

## 8. API Contract

All routes are under `/textbooks/api` when deployed and `/api` inside the application router.

- `GET /health` returns app, database, index, Ollama, and NVIDIA configuration status without secrets.
- `GET /sources` returns catalog and indexing status.
- `POST /query` accepts `question`, `provider`, optional `course_ids`, optional `source_ids`, and optional `conversation_id`; returns answer status, answer text, citations, evidence, provider outcome, and conversation/message IDs.
- `GET /conversations` lists local conversation summaries newest first.
- `GET /conversations/{id}` returns messages and evidence references.
- `DELETE /conversations/{id}` deletes one conversation and its messages only.
- `DELETE /conversations` requires `confirm=true` and deletes all conversation/message rows only.
- `GET /sources/{source_id}/pdf` streams the configured original PDF with range support.

Requests are size-limited and validated. Error responses distinguish invalid input, insufficient evidence, provider unavailable, retrieval unavailable, and internal errors.

## 9. Data Model

- `sources`: catalog identity, file hash/path, page count, extraction/index versions, status.
- `source_courses`: many-to-many source/course mapping.
- `pages`: source physical page, page label, raw/cleaned text, extraction settings, and diagnostics.
- `chunks`: page-aware content, ordinal, hash, embedding blob, embedding dimension.
- `chunks_fts`: FTS5 virtual table mirroring chunk content.
- `conversations`: local title and timestamps.
- `messages`: role, text, provider choice/actual provider, fallback flag, status, timestamps.
- `message_evidence`: retrieved chunk IDs, rank, scores, and citation order.

Foreign keys and cascading deletes apply only inside the conversation aggregate. Deleting history must not delete source/index rows or PDFs.

## 10. Product Experience

The visual contract is the Figma file `VOfLyXbC90Xz8TlyjfqkVD`, page `Product UI`, desktop frame `7:3`, and mobile frame `7:4`.

- Desktop uses a history rail, central answer/composer, and evidence/PDF panel.
- Mobile uses a compact top bar, dismissible fallback banner, scrollable answer, evidence bottom sheet, and fixed composer.
- The provider control is visible at query time.
- Citation controls are keyboard accessible and open the original PDF to the cited page inside the app.
- Loading preserves the current question and shows retrieval/generation progress without fake completion percentages.
- Insufficient evidence is a clear answer state, not a generic error.
- Individual deletion is available from a conversation action. Clear-all uses a confirmation dialog naming the irreversible local-history effect.
- Minimum touch target is 44 CSS pixels; focus is always visible; color is never the only state signal.

## 11. Security and Privacy

- The HTTP server binds to loopback only.
- Tailscale Serve, not Funnel, is the remote ingress.
- NVIDIA mode sends the question and retrieved excerpts to NVIDIA; the UI makes the selected provider and actual provider visible.
- PDFs, database, generated indexes, logs, and dotenv files are ignored by Git.
- Logs exclude API keys and avoid full textbook passages and full answers by default.
- PDF serving is allowlist-based from the catalog and prevents path traversal.

## 12. Deployment

- The app listens on `127.0.0.1:8766`.
- Tailscale Serve adds `/textbooks -> http://127.0.0.1:8766/textbooks` while preserving `/ -> http://127.0.0.1:8787`.
- Windows scheduled tasks start the SSH tunnel and application at user logon with restart-on-failure behavior.
- Setup scripts are idempotent and include inspection/rollback commands. They do not overwrite the existing root Serve mapping.

## 13. Acceptance Gates

- All four PDFs ingest, with a report that calls out suspicious pages.
- Retrieval evaluation covers at least 12 answerable and 6 intentionally unsupported questions across all sources/courses.
- Answerable questions retrieve supporting pages in the final evidence set at the agreed pass rate recorded in the evaluation report.
- Unsupported questions abstain without provider calls.
- NVIDIA, Ollama, Auto success, Auto fallback, and explicit-provider failure behavior pass automated tests.
- Citation IDs always resolve to returned evidence and the exact original PDF page.
- Conversation create/read/delete-one/delete-all behavior passes API and UI tests.
- Frontend build/typecheck and backend tests pass.
- Desktop and 390px mobile browser checks cover loading, answer, fallback, insufficient evidence, deletion confirmation, and PDF viewing.
- Live validation proves the existing Serve root remains reachable and `/textbooks` works through the tailnet.

## 14. Deliverables

- Source code, tests, configuration, and scripts.
- `README.md` with local development, ingestion, deployment, recovery, and model setup.
- Ingestion and retrieval evaluation reports.
- ImageGen concepts and validated Figma/browser screenshots plus a final fidelity ledger.
