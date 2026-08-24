# TRAG-002 - Hybrid retrieval and grounded providers

## Goal

Implement filtered hybrid retrieval, strict evidence gating, NVIDIA/Ollama adapters, and the exact Auto fallback contract.

## Dependencies

TRAG-001.

## Acceptance Criteria

- FTS and cosine candidates are fused with deterministic ranks and exact source/page metadata.
- Course and source filters apply before final ranking.
- Unsupported retrieval returns `insufficient_evidence` without invoking generation.
- NVIDIA defaults to `nvidia/nemotron-3-super-120b-a12b`; Ollama uses `qwen3.5:9b`.
- Auto falls back only on classified provider failures; explicit providers never switch.
- Provider output citations are validated against retrieved chunk IDs.
- Tests cover both providers, success/failure classification, Auto fallback, explicit failure, abstention, and invalid citations.

