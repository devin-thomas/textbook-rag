# Architecture Decision Record

## ADR-001 - Preserve page-level textbook provenance

**Status:** Accepted

**Decision:** Every retrievable chunk must retain its source identity and original one-based PDF page number through ingestion, retrieval, and answer generation.

**Rationale:** The study assistant must let the student verify claims against assigned material, and extraction quality varies across the source PDFs.

**Consequences:** Ingestion cannot discard page boundaries or replace original coordinates with only internal chunk identifiers. Citation rendering and evaluation can rely on stable source/page metadata.

## ADR-002 - Select application and model boundaries during discovery

**Status:** Superseded by ADR-003, ADR-004, and ADR-005

**Decision:** Do not select the user interface, hosting boundary, model provider, embedding provider, or search database until the first discovery round resolves privacy and usage requirements.

**Rationale:** These choices determine cost, setup complexity, hardware requirements, data exposure, and whether the tool is usable away from the development machine.

**Consequences:** Initial inspection may evaluate document quality, but implementation and the final architecture model wait for explicit user decisions.

## ADR-003 - Host a loopback-only web app behind Tailscale Serve

**Status:** Accepted

**Decision:** Run the textbook application locally on `titan`, bind its HTTP server to loopback, and expose it privately to the user's phone through Tailscale Serve. Do not create a public Funnel route.

**Rationale:** The user wants a simple local deployment that remains reachable away from home without publishing the textbooks or application to the public internet.

**Consequences:** Availability depends on `titan` being powered on and connected unless a later deployment decision changes the host. Tailscale identity and policy form the remote-access boundary. The existing root Serve route must be preserved or deliberately replaced.

## ADR-004 - Require textbook-only grounded answers

**Status:** Accepted

**Decision:** Answer factual questions only from retrieved passages in the indexed textbooks and explicitly report insufficient textbook evidence when retrieval cannot support an answer.

**Rationale:** The user values confidence that answers come from assigned material over broader model knowledge.

**Consequences:** Prompting, citations, and tests must enforce abstention. A fluent model response without supporting source chunks is a failure.

## ADR-005 - Use remote Ollama as primary inference with optional NVIDIA evaluation

**Status:** Superseded by ADR-006

**Decision:** Use Ollama on the `research` Mac as the primary generation boundary. Keep NVIDIA-hosted models optional and evaluate them through the user's existing OpenAI-compatible client before deciding whether they appear in normal product use.

**Rationale:** Local inference keeps the books private and reuses existing hardware. NVIDIA's hosted free endpoints offer useful comparison models but have external-data and unstable-quota tradeoffs.

**Consequences:** The app needs an explicit, failure-visible connection from `titan` to the loopback-bound Ollama service on `research`. NVIDIA credentials remain in ignored local environment files and are never sent to the browser.

## ADR-006 - Route each query through selectable NVIDIA and Ollama providers

**Status:** Accepted

**Decision:** Provide `Auto`, `NVIDIA`, and `Ollama` choices on each query. `Auto` sends generation to NVIDIA first and retries with Ollama only when NVIDIA fails. Explicit provider choices do not silently switch providers.

**Rationale:** The user wants NVIDIA's hosted models used automatically while retaining predictable per-query control and a local failure path.

**Consequences:** In `Auto` and `NVIDIA` modes, the question and retrieved textbook passages leave the tailnet for NVIDIA's hosted API. The answer must show which provider actually produced it. Provider failure and fallback are observable; an unsupported textbook answer is not a provider failure and must not trigger fallback.

## ADR-007 - Preserve the existing Serve root and auto-start the textbook app

**Status:** Accepted

**Decision:** Mount the textbook application at `/textbooks` on Titan's existing Tailscale Serve HTTPS endpoint. Configure the local app and its SSH tunnel to start automatically on `titan`.

**Rationale:** The root path already hosts the user's NVIDIA dialogue dashboard, and the textbook app should be available remotely without a manual launch step.

**Consequences:** The backend must support path-prefix deployment. The service remains unavailable while `titan` is asleep or off. Deployment validation must prove that both `/` and `/textbooks` work after configuration.

## ADR-008 - Store deletable conversation history on Titan

**Status:** Accepted

**Decision:** Persist textbook conversations only on `titan` and expose user-controlled deletion from the application.

**Rationale:** Persistent history makes phone and desktop study sessions continuous without moving chat records to a hosted database.

**Consequences:** Conversation records need stable identifiers and deletion behavior. Secrets and raw provider credentials are never part of stored conversation data.

## ADR-009 - Use dedicated Qwen models for local generation and retrieval

**Status:** Accepted

**Decision:** Use `qwen3.5:9b` for Ollama generation and `qwen3-embedding:4b` for local semantic embeddings on `research`.

**Rationale:** The M4 Pro host has 48 GB of memory but limited free storage. The selected models provide a general-purpose generation model and a retrieval-specific embedding model in approximately 8.5 GB total model storage.

**Consequences:** The embedding index is coupled to the 2,560-dimension output of `qwen3-embedding:4b` and must be rebuilt if the embedding model changes. The previous `qwen3-coder-agent:latest` and `qwen3-coder:30b` models were deleted with explicit user authorization and require re-download to restore.

## ADR-010 - Keep retrieval embeddings local and provider-independent

**Status:** Accepted

**Decision:** Generate document and query embeddings only with `qwen3-embedding:4b` on `research`, regardless of whether NVIDIA or Ollama generates the final answer.

**Rationale:** One local embedding space produces a stable index, avoids uploading the corpus in bulk, and keeps provider selection from changing retrieval semantics.

**Consequences:** Changing the embedding model requires a full index rebuild. If local embedding inference is unavailable, the application must surface retrieval unavailability rather than switching embedding spaces silently.

## ADR-011 - Make evidence directly inspectable

**Status:** Accepted

**Decision:** Render concise answers with source/page citations, expandable retrieved evidence, and an in-app viewer that opens the original PDF at the cited page.

**Rationale:** The user wants textbook-only confidence and an easy way to verify each answer against assigned material.

**Consequences:** The backend must preserve original PDF page coordinates and serve only configured corpus PDFs. The frontend must render PDF pages reliably on phone and desktop.

## ADR-012 - Support scoped and bulk history deletion

**Status:** Accepted

**Decision:** Allow deletion of one conversation and deletion of all conversations. Bulk deletion requires explicit confirmation.

**Rationale:** Locally persisted study history is useful, but the user must retain straightforward control over stored records.

**Consequences:** Deletion APIs must be explicit and testable. Deleting conversation history must not delete textbooks, chunks, embeddings, or source metadata.

## ADR-013 - Separate citation labels from physical PDF coordinates

**Status:** Accepted

**Decision:** Persist both the one-based physical PDF page and the document page label. Display the page label in citation copy when available, but navigate the in-app viewer by the physical page.

**Rationale:** The corpus contains front matter that shifts printed labels from PDF indices. For example, Guide to Parallel Operating Systems physical page 339 is labeled 317.

**Consequences:** Ingestion uses `pypdf` page labels alongside `pdfplumber` extraction. Retrieval, history, and API responses carry both values; tests verify that citation display and viewer navigation cannot be conflated.

## ADR-014 - Keep NVIDIA answers available when semantic retrieval is offline

**Status:** Accepted

**Decision:** When the local Qwen query-embedding request fails, `NVIDIA` and `Auto` may retrieve evidence through the existing SQLite FTS index and continue to generation. Explicit `Ollama` requests continue to surface retrieval unavailability.

**Rationale:** The indexed textbook chunks already have a deterministic lexical search path. Preserving that path lets the selected NVIDIA provider answer when Research is temporarily unreachable without mixing embedding spaces or uploading the corpus to another embedding service.

**Consequences:** FTS-only answers may be less effective for paraphrased questions, so the API and saved message expose a retrieval-fallback flag and the UI identifies the degraded mode. Ingestion still requires Ollama embeddings, and a malformed or dimension-incompatible index remains a hard failure.
