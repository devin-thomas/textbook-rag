from __future__ import annotations

from dataclasses import replace
import json

import httpx
import numpy as np
import pytest

from textbook_rag.providers import (
    GeneratedAnswer,
    GroundingFailure,
    ProviderFailure,
    ProviderRouter,
    ProviderScope,
    NvidiaProvider,
    _decode_answer,
)
from textbook_rag.embeddings import EmbeddingError
from textbook_rag.retrieval import Evidence, HybridRetriever, outside_static_textbook_scope

from conftest import FakeEmbeddings


def test_hybrid_retrieval_filters_before_ranking(seeded_database) -> None:
    database, _catalog = seeded_database
    embeddings = FakeEmbeddings({"virtual memory": [1.0, 0.0, 0.0]})
    retriever = HybridRetriever(database, embeddings, min_semantic_score=.5)
    result = retriever.retrieve("virtual memory", source_ids=("book-0",))
    assert result.status == "ok"
    assert [item.chunk_id for item in result.evidence] == ["chunk-0"]
    assert result.evidence[0].physical_page == 4
    assert result.evidence[0].page_label == "P-0"


def test_low_similarity_abstains_without_evidence(seeded_database) -> None:
    database, _catalog = seeded_database
    embeddings = FakeEmbeddings({"cafeteria hours": [0.0, 0.0, 1.0]})
    result = HybridRetriever(database, embeddings, min_semantic_score=.5).retrieve("cafeteria hours")
    assert result.status == "insufficient_evidence"
    assert result.evidence == ()


def test_embedding_failure_can_fall_back_to_fts_for_nvidia(seeded_database) -> None:
    database, _catalog = seeded_database
    embeddings = FakeEmbeddings()

    def fail(_texts):
        raise EmbeddingError("Ollama embedding request failed")

    embeddings.embed = fail
    result = HybridRetriever(database, embeddings, min_semantic_score=.5).retrieve(
        "virtual memory", allow_semantic_fallback=True
    )

    assert result.status == "ok"
    assert result.semantic_fallback_used is True
    assert result.top_semantic_score is None
    assert result.evidence[0].chunk_id == "chunk-0"
    assert result.evidence[0].semantic_score is None
    assert result.evidence[0].fts_score is not None


def test_embedding_failure_still_raises_without_fallback_permission(seeded_database) -> None:
    database, _catalog = seeded_database
    embeddings = FakeEmbeddings()

    def fail(_texts):
        raise EmbeddingError("Ollama embedding request failed")

    embeddings.embed = fail
    with pytest.raises(EmbeddingError, match="Ollama embedding request failed"):
        HybridRetriever(database, embeddings).retrieve("virtual memory")


@pytest.mark.parametrize(
    "question",
    [
        "What grade did I receive on my assignment?",
        "What is my professor's email?",
        "When is the midterm this semester?",
        "What is the newest stable React version available today?",
        "Which GPU is hosting this app?",
        "When does the campus cafeteria close?",
    ],
)
def test_dynamic_or_personal_questions_are_outside_static_textbook_scope(question: str) -> None:
    assert outside_static_textbook_scope(question)


def test_current_word_alone_does_not_trigger_scope_gate() -> None:
    assert not outside_static_textbook_scope("How does current flow through this circuit?")
    assert not outside_static_textbook_scope("What is the latest edition discussed in the textbook?")


class StubProvider:
    def __init__(self, name, answer=None, failure=None):
        self.name = name
        self.answer = answer
        self.failure = failure
        self.calls = 0

    def generate(self, _question, _evidence, _scope=None):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.answer


def test_auto_falls_back_only_for_retryable_provider_failure() -> None:
    answer = GeneratedAnswer("ok", "Grounded.", ("chunk-0",))
    nvidia = StubProvider("nvidia", failure=ProviderFailure("nvidia", "timeout", "timeout", retryable=True))
    ollama = StubProvider("ollama", answer=answer)
    result = ProviderRouter(nvidia, ollama).generate("auto", "question", ())
    assert result.actual_provider == "ollama"
    assert result.fallback_used is True
    assert nvidia.calls == ollama.calls == 1


def test_explicit_provider_never_switches() -> None:
    failure = ProviderFailure("nvidia", "timeout", "timeout", retryable=True)
    nvidia = StubProvider("nvidia", failure=failure)
    ollama = StubProvider("ollama", answer=GeneratedAnswer("ok", "answer", ("chunk-0",)))
    with pytest.raises(ProviderFailure):
        ProviderRouter(nvidia, ollama).generate("nvidia", "question", ())
    assert nvidia.calls == 1
    assert ollama.calls == 0


def test_auto_does_not_fallback_for_non_retryable_rejection() -> None:
    nvidia = StubProvider(
        "nvidia", failure=ProviderFailure("nvidia", "request_rejected", "bad request", retryable=False)
    )
    ollama = StubProvider("ollama", answer=GeneratedAnswer("ok", "answer", ("chunk-0",)))
    with pytest.raises(ProviderFailure):
        ProviderRouter(nvidia, ollama).generate("auto", "question", ())
    assert ollama.calls == 0


def test_invalid_provider_citation_is_rejected() -> None:
    evidence = (
        Evidence("chunk-0", "book-0", "Book", 4, "4", "excerpt", 1, .9, 1.0, .03),
    )
    with pytest.raises(GroundingFailure, match="not retrieved"):
        _decode_answer(
            "nvidia",
            '{"status":"ok","answer":"Claim.","citations":["invented"]}',
            evidence,
        )


def test_valid_provider_abstention_is_not_a_failure() -> None:
    evidence = (
        Evidence("chunk-0", "book-0", "Book", 4, "4", "excerpt", 1, .9, 1.0, .03),
    )
    answer = _decode_answer(
        "ollama",
        '{"status":"insufficient_evidence","answer":"Not enough information.","citations":[]}',
        evidence,
    )
    assert answer.status == "insufficient_evidence"


def test_decode_answer_ignores_embedded_draft_before_final_json() -> None:
    evidence = (
        Evidence("chunk-0", "book-0", "Book", 4, "4", "excerpt", 1, .9, 1.0, .03),
    )

    answer = _decode_answer(
        "nvidia",
        (
            '<think>{"status":"ok","answer":"Draft.","citations":["chunk-0"]}</think>\n'
            '```json\n{"status":"ok","answer":"Grounded.","citations":["chunk-0"]}\n```'
        ),
        evidence,
    )

    assert answer.answer == "Grounded."
    assert answer.cited_chunk_ids == ("chunk-0",)


def test_auto_does_not_fallback_for_invalid_citations() -> None:
    failure = GroundingFailure(
        "nvidia", "invalid_citations", "provider cited unretreived evidence", retryable=False
    )
    nvidia = StubProvider("nvidia", failure=failure)
    ollama = StubProvider("ollama", answer=GeneratedAnswer("ok", "answer", ("chunk-0",)))
    with pytest.raises(GroundingFailure):
        ProviderRouter(nvidia, ollama).generate("auto", "question", ())
    assert ollama.calls == 0


def test_auto_falls_back_when_provider_returns_non_object_json() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, json={"choices": [{"message": {"content": "[]"}}]}
        )
    )
    nvidia = NvidiaProvider(
        "https://provider.example/v1",
        "model",
        "test-key",
        client=httpx.Client(transport=transport),
    )
    ollama = StubProvider(
        "ollama", answer=GeneratedAnswer("ok", "Grounded.", ("chunk-0",))
    )

    result = ProviderRouter(nvidia, ollama).generate("auto", "question", ())

    assert result.actual_provider == "ollama"
    assert result.fallback_used is True
    assert result.initial_failure_kind == "malformed_response"


def test_provider_abstention_requires_non_empty_explanation() -> None:
    with pytest.raises(GroundingFailure, match="abstention requires an explanation"):
        _decode_answer(
            "ollama",
            '{"status":"insufficient_evidence","answer":"","citations":[]}',
            (),
        )


def test_provider_prompt_includes_selected_scope_ids_and_labels() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"status":"insufficient_evidence",'
                                '"answer":"Not enough textbook evidence.","citations":[]}'
                            )
                        }
                    }
                ]
            },
        )

    provider = NvidiaProvider(
        "https://provider.example/v1",
        "model",
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    scope = ProviderScope(
        sources=(("book-0", "Book 0"),),
        courses=(("COURSE-1", "Course One"),),
        select_all_that_apply=True,
    )

    provider.generate("question", (), scope)

    prompt = captured["messages"][1]["content"]
    assert "book-0: Book 0" in prompt
    assert "COURSE-1: Course One" in prompt
    system_prompt = captured["messages"][0]["content"]
    assert "answer text must not contain chunk IDs" in system_prompt
    assert "SELECT ALL THAT APPLY" in system_prompt
    assert "every distinct correct option" in system_prompt


def test_removed_catalog_source_is_retired_and_not_retrieved(seeded_database) -> None:
    database, catalog = seeded_database
    reduced = type(catalog)(root=catalog.root, courses=catalog.courses, sources=(catalog.sources[0],))
    database.initialize(reduced)
    with database.connect() as connection:
        status = connection.execute("SELECT status FROM sources WHERE id='book-1'").fetchone()[0]
    assert status == "retired"
    embeddings = FakeEmbeddings({"semantic html": [0.0, 1.0, 0.0]})
    result = HybridRetriever(database, embeddings, min_semantic_score=.5).retrieve("semantic html")
    assert all(item.source_id != "book-1" for item in result.evidence)


def test_retired_sources_do_not_consume_fts_candidate_limit(seeded_database) -> None:
    database, catalog = seeded_database
    reduced = type(catalog)(root=catalog.root, courses=catalog.courses, sources=(catalog.sources[0],))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE chunks SET content='virtual memory' WHERE id='chunk-1'"
        )
        connection.execute("DELETE FROM chunks_fts WHERE chunk_id='chunk-1'")
        connection.execute(
            "INSERT INTO chunks_fts(chunk_id, source_id, physical_page, content) "
            "VALUES ('chunk-1', 'book-1', 4, 'virtual memory')"
        )
    database.initialize(reduced)
    embeddings = FakeEmbeddings({"virtual memory": [1.0, 0.0, 0.0]})

    result = HybridRetriever(
        database, embeddings, min_semantic_score=.5, fts_candidates=1
    ).retrieve("virtual memory")

    assert result.evidence[0].source_id == "book-0"
    assert result.evidence[0].fts_score is not None


def test_course_filter_returns_source_shared_with_that_course(seeded_database) -> None:
    database, catalog = seeded_database
    course_type = type(catalog.courses[0])
    shared_catalog = type(catalog)(
        root=catalog.root,
        courses=(*catalog.courses, course_type("COURSE-2", "Course Two")),
        sources=(
            replace(catalog.sources[0], course_ids=("COURSE-1", "COURSE-2")),
            catalog.sources[1],
        ),
    )
    database.initialize(shared_catalog)
    embeddings = FakeEmbeddings({"virtual memory": [1.0, 0.0, 0.0]})

    result = HybridRetriever(database, embeddings, min_semantic_score=.5).retrieve(
        "virtual memory", course_ids=("COURSE-2",)
    )

    assert [item.source_id for item in result.evidence] == ["book-0"]


def test_textbook_adjacent_but_unsupported_question_still_abstains(seeded_database) -> None:
    database, _catalog = seeded_database
    embeddings = FakeEmbeddings(
        {"How should I configure virtual memory for this campus lab today?": [0.0, 0.0, 1.0]}
    )

    result = HybridRetriever(database, embeddings, min_semantic_score=.5).retrieve(
        "How should I configure virtual memory for this campus lab today?"
    )

    assert result.status == "insufficient_evidence"
    assert result.evidence == ()


def test_near_tied_evidence_prefers_source_diversity_without_dropping_adjacent_passages(
    seeded_database,
) -> None:
    database, _catalog = seeded_database
    content = "Virtual memory pages handle a page fault."
    vector = np.asarray([1.0, 0.0, 0.0], dtype="<f4").tobytes()
    with database.transaction() as connection:
        connection.execute(
            "UPDATE chunks SET content=?, embedding=? WHERE id='chunk-1'",
            (content, vector),
        )
        page_id = connection.execute(
            "SELECT page_id FROM chunks WHERE id='chunk-0'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO chunks(id, source_id, page_id, physical_page, page_label, ordinal, "
            "char_start, char_end, content, content_sha256, embedding, embedding_dimension) "
            "VALUES ('chunk-0b', 'book-0', ?, 4, 'P-0', 1, 0, ?, ?, 'hash-0b', ?, 3)",
            (page_id, len(content), content, vector),
        )
        connection.execute("DELETE FROM chunks_fts")
        connection.executemany(
            "INSERT INTO chunks_fts(chunk_id, source_id, physical_page, content) VALUES (?, ?, 4, ?)",
            (
                ("chunk-0", "book-0", content),
                ("chunk-0b", "book-0", content),
                ("chunk-1", "book-1", content),
            ),
        )
    embeddings = FakeEmbeddings({"virtual memory": [1.0, 0.0, 0.0]})

    result = HybridRetriever(
        database, embeddings, min_semantic_score=.5, final_chunks=3
    ).retrieve("virtual memory")

    assert [item.source_id for item in result.evidence[:2]] == ["book-0", "book-1"]
    assert {item.chunk_id for item in result.evidence} == {"chunk-0", "chunk-0b", "chunk-1"}
