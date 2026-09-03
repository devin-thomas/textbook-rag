from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
import sqlite3
from typing import Any

import numpy as np

from .db import Database
from .embeddings import EmbeddingError, OllamaEmbeddingClient


_DIVERSITY_NEAR_TIE_RATIO = 0.95


@dataclass(frozen=True, slots=True)
class Evidence:
    chunk_id: str
    source_id: str
    source_title: str
    physical_page: int
    page_label: str
    excerpt: str
    rank: int
    semantic_score: float | None
    fts_score: float | None
    fusion_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    status: str
    evidence: tuple[Evidence, ...]
    top_semantic_score: float | None
    semantic_fallback_used: bool = False


def _scope_clause(
    source_ids: tuple[str, ...], course_ids: tuple[str, ...], *, alias: str = "c"
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    if source_ids:
        placeholders = ",".join("?" for _ in source_ids)
        clauses.append(f"{alias}.source_id IN ({placeholders})")
        params.extend(source_ids)
    if course_ids:
        placeholders = ",".join("?" for _ in course_ids)
        clauses.append(
            f"EXISTS (SELECT 1 FROM source_courses sc WHERE sc.source_id={alias}.source_id "
            f"AND sc.course_id IN ({placeholders}))"
        )
        params.extend(course_ids)
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _fts_expression(question: str) -> str | None:
    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for",
        "from", "how", "i", "in", "is", "it", "my", "of", "on", "or", "that", "the",
        "this", "to", "was", "what", "when", "where", "which", "why", "with",
    }
    terms = []
    seen: set[str] = set()
    for term in re.findall(r"[\w]+", question.casefold(), flags=re.UNICODE):
        if len(term) < 2 or term in seen or term in stop_words:
            continue
        seen.add(term)
        terms.append('"' + term.replace('"', '""') + '"')
    return " OR ".join(terms[:24]) or None


def outside_static_textbook_scope(question: str) -> bool:
    """Reject requests whose answer necessarily depends on personal or live state."""
    normalized = " ".join(question.casefold().split())
    personal_record = re.search(
        r"\b(?:my|our)\b.{0,80}\b(?:grade|score|assignment|exam|midterm|final|schedule|"
        r"professor|instructor|email|class|course)\b",
        normalized,
    )
    local_logistics = re.search(
        r"\b(?:this semester|campus cafeteria|professor(?:'s)? email|instructor(?:'s)? email)\b",
        normalized,
    )
    runtime_state = re.search(
        r"\b(?:this app|this request|model request|hosting this|host this)\b", normalized
    )
    live_information = re.search(
        r"\b(?:newest|latest|today|right now|current(?:ly)? available|current version)\b",
        normalized,
    )
    explicitly_textual = re.search(
        r"\b(?:according to|the textbook|this textbook|the book|this book|the chapter|the author)\b",
        normalized,
    )
    return bool(
        personal_record
        or local_logistics
        or runtime_state
        or (live_information and not explicitly_textual)
    )


class HybridRetriever:
    def __init__(
        self,
        database: Database,
        embeddings: OllamaEmbeddingClient,
        *,
        semantic_candidates: int = 24,
        fts_candidates: int = 24,
        final_chunks: int = 8,
        min_semantic_score: float = 0.18,
        rrf_k: int = 60,
    ) -> None:
        self.database = database
        self.embeddings = embeddings
        self.semantic_candidates = semantic_candidates
        self.fts_candidates = fts_candidates
        self.final_chunks = final_chunks
        self.min_semantic_score = min_semantic_score
        self.rrf_k = rrf_k

    def retrieve(
        self,
        question: str,
        *,
        source_ids: tuple[str, ...] = (),
        course_ids: tuple[str, ...] = (),
        allow_semantic_fallback: bool = False,
    ) -> RetrievalResult:
        if outside_static_textbook_scope(question):
            return RetrievalResult("insufficient_evidence", (), None)
        scope_sql, scope_params = _scope_clause(source_ids, course_ids)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT c.id, c.source_id, s.title AS source_title, c.physical_page, "
                "c.page_label, c.content, c.embedding, c.embedding_dimension "
                "FROM chunks c JOIN sources s ON s.id=c.source_id WHERE s.status='ready'"
                + scope_sql
                + " ORDER BY c.id",
                scope_params,
            ).fetchall()
            if not rows:
                return RetrievalResult("insufficient_evidence", (), None)
            semantic_rank: dict[str, int] = {}
            semantic_score: dict[str, float] = {}
            semantic_fallback_used = False
            try:
                dimensions = {int(row["embedding_dimension"]) for row in rows}
                if dimensions != {self.embeddings.expected_dimension}:
                    raise RuntimeError("index contains an unexpected embedding dimension")
                query = self.embeddings.embed([question])[0]
                matrix = np.vstack(
                    [
                        np.frombuffer(
                            row["embedding"],
                            dtype="<f4",
                            count=self.embeddings.expected_dimension,
                        )
                        for row in rows
                    ]
                )
                matrix_norms = np.linalg.norm(matrix, axis=1)
                query_norm = float(np.linalg.norm(query))
                denominators = matrix_norms * query_norm
                similarities = np.divide(
                    matrix @ query,
                    denominators,
                    out=np.zeros(len(rows), dtype=np.float32),
                    where=denominators > 0,
                )
                semantic_order = sorted(
                    range(len(rows)),
                    key=lambda index: (-float(similarities[index]), rows[index]["id"]),
                )[: self.semantic_candidates]
                semantic_rank = {
                    rows[index]["id"]: rank
                    for rank, index in enumerate(semantic_order, 1)
                }
                semantic_score = {
                    rows[index]["id"]: float(similarities[index])
                    for index in semantic_order
                }
            except EmbeddingError:
                if not allow_semantic_fallback:
                    raise
                semantic_fallback_used = True

            fts_score: dict[str, float] = {}
            fts_rank: dict[str, int] = {}
            expression = _fts_expression(question)
            if expression:
                fts_scope_sql, fts_scope_params = _scope_clause(source_ids, course_ids, alias="c")
                try:
                    fts_rows = connection.execute(
                        "SELECT c.id, bm25(chunks_fts) AS raw_score FROM chunks_fts "
                        "JOIN chunks c ON c.id=chunks_fts.chunk_id "
                        "JOIN sources s ON s.id=c.source_id "
                        "WHERE chunks_fts MATCH ? AND s.status='ready'"
                        + fts_scope_sql
                        + " ORDER BY raw_score, c.id LIMIT ?",
                        [expression, *fts_scope_params, self.fts_candidates],
                    ).fetchall()
                except sqlite3.OperationalError as exc:
                    raise RuntimeError(f"FTS retrieval failed: {exc}") from exc
                for rank, row in enumerate(fts_rows, 1):
                    fts_rank[row["id"]] = rank
                    fts_score[row["id"]] = -float(row["raw_score"])

        top_semantic = max(semantic_score.values(), default=None)
        if semantic_fallback_used and not fts_rank:
            return RetrievalResult("insufficient_evidence", (), None, True)
        if not semantic_fallback_used and (
            top_semantic is None or top_semantic < self.min_semantic_score
        ):
            return RetrievalResult("insufficient_evidence", (), top_semantic)
        fused: dict[str, float] = {}
        for chunk_id, rank in semantic_rank.items():
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (self.rrf_k + rank)
        for chunk_id, rank in fts_rank.items():
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (self.rrf_k + rank)
        row_by_id = {row["id"]: row for row in rows}
        ranked = sorted(
            (chunk_id for chunk_id in fused if chunk_id in row_by_id),
            key=lambda chunk_id: (-fused[chunk_id], chunk_id),
        )
        ordered: list[str] = []
        seen_sources: set[str] = set()
        seen_pages: set[tuple[str, int]] = set()
        while ranked and len(ordered) < self.final_chunks:
            best_score = fused[ranked[0]]
            near_tied = [
                chunk_id
                for chunk_id in ranked
                if fused[chunk_id] >= best_score * _DIVERSITY_NEAR_TIE_RATIO
            ]
            chunk_id = min(
                near_tied,
                key=lambda candidate: (
                    row_by_id[candidate]["source_id"] in seen_sources,
                    (
                        row_by_id[candidate]["source_id"],
                        int(row_by_id[candidate]["physical_page"]),
                    )
                    in seen_pages,
                    -fused[candidate],
                    candidate,
                ),
            )
            ranked.remove(chunk_id)
            ordered.append(chunk_id)
            source_id = row_by_id[chunk_id]["source_id"]
            seen_sources.add(source_id)
            seen_pages.add((source_id, int(row_by_id[chunk_id]["physical_page"])))
        evidence = tuple(
            Evidence(
                chunk_id=chunk_id,
                source_id=row_by_id[chunk_id]["source_id"],
                source_title=row_by_id[chunk_id]["source_title"],
                physical_page=int(row_by_id[chunk_id]["physical_page"]),
                page_label=row_by_id[chunk_id]["page_label"],
                excerpt=row_by_id[chunk_id]["content"],
                rank=rank,
                semantic_score=semantic_score.get(chunk_id),
                fts_score=fts_score.get(chunk_id),
                fusion_score=fused[chunk_id],
            )
            for rank, chunk_id in enumerate(ordered, 1)
        )
        return RetrievalResult("ok", evidence, top_semantic, semantic_fallback_used)
