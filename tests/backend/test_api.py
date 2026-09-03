from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from textbook_rag.app import Runtime, create_app
from textbook_rag.history import HistoryStore
from textbook_rag.providers import GeneratedAnswer, ProviderRouter
from textbook_rag.retrieval import HybridRetriever
from textbook_rag.service import QueryService
from textbook_rag.settings import Settings

from conftest import FakeEmbeddings


class AnswerProvider:
    def __init__(self, name: str, chunk_id: str):
        self.name = name
        self.chunk_id = chunk_id
        self.calls = 0
        self.scopes = []

    def generate(self, _question, _evidence, scope=None):
        self.calls += 1
        self.scopes.append(scope)
        return GeneratedAnswer("ok", "A page fault loads the page into physical memory.", (self.chunk_id,))


def make_client(seeded_database):
    database, catalog = seeded_database
    embeddings = FakeEmbeddings(
        {"virtual memory": [1.0, 0.0, 0.0], "cafeteria hours": [0.0, 0.0, 1.0]}
    )
    retriever = HybridRetriever(database, embeddings, min_semantic_score=.5)
    nvidia = AnswerProvider("nvidia", "chunk-0")
    ollama = AnswerProvider("ollama", "chunk-0")
    providers = ProviderRouter(nvidia, ollama)
    history = HistoryStore(database)
    settings = replace(
        Settings.from_env(catalog.root),
        catalog_path=catalog.root / "sources.json",
        database_path=database.path,
        embedding_dimension=3,
        max_question_chars=100,
    )
    runtime = Runtime(
        settings,
        catalog,
        database,
        embeddings,
        retriever,
        history,
        providers,
        QueryService(catalog, retriever, providers, history),
    )
    return TestClient(create_app(runtime)), database, nvidia, ollama


def test_health_and_source_contract_at_both_prefixes(seeded_database) -> None:
    client, _database, _nvidia, _ollama = make_client(seeded_database)
    assert client.get("/api/health").status_code == 200
    deployed = client.get("/textbooks/api/sources")
    assert deployed.status_code == 200
    assert {source["id"] for source in deployed.json()["sources"]} == {"book-0", "book-1"}


def test_health_counts_only_current_catalog_sources_and_chunks(seeded_database) -> None:
    database, catalog = seeded_database
    reduced = type(catalog)(root=catalog.root, courses=catalog.courses, sources=(catalog.sources[0],))
    database.initialize(reduced)
    client, _database, _nvidia, _ollama = make_client((database, reduced))

    health = client.get("/api/health").json()["index"]

    assert health == {
        "status": "ready",
        "ready_sources": 1,
        "configured_sources": 1,
        "chunks": 1,
    }


def test_database_migrates_initial_failure_metadata_column(seeded_database) -> None:
    database, catalog = seeded_database
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version=4")
        connection.execute("ALTER TABLE messages DROP COLUMN initial_failure_kind")
        connection.commit()

    database.initialize(catalog)

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        migration = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=4"
        ).fetchone()
    assert "initial_failure_kind" in columns
    assert migration is not None


def test_database_migrates_retrieval_fallback_metadata_column(seeded_database) -> None:
    database, catalog = seeded_database
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version=5")
        connection.execute("ALTER TABLE messages DROP COLUMN retrieval_fallback_used")
        connection.commit()

    database.initialize(catalog)

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        migration = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=5"
        ).fetchone()
    assert "retrieval_fallback_used" in columns
    assert migration is not None


def test_database_migrates_select_all_mode_column(seeded_database) -> None:
    database, catalog = seeded_database
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version=6")
        connection.execute("ALTER TABLE messages DROP COLUMN select_all_that_apply")
        connection.commit()

    database.initialize(catalog)

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        migration = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=6"
        ).fetchone()
    assert "select_all_that_apply" in columns
    assert migration is not None


def test_database_migrates_conversation_course_scope_column(seeded_database) -> None:
    database, catalog = seeded_database
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version=7")
        connection.execute("ALTER TABLE conversations DROP COLUMN course_ids")
        connection.commit()

    database.initialize(catalog)

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        migration = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=7"
        ).fetchone()
    assert "course_ids" in columns
    assert migration is not None


def test_database_backfills_legacy_conversation_course_scope_from_evidence(seeded_database) -> None:
    client, database, _nvidia, _ollama = make_client(seeded_database)
    query = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": "nvidia", "source_ids": ["book-0"]},
    )
    assert query.status_code == 200
    conversation_id = query.json()["conversation_id"]

    with database.transaction() as connection:
        connection.execute(
            "UPDATE conversations SET course_ids='[]' WHERE id=?", (conversation_id,)
        )
    database.initialize(seeded_database[1])

    summary = next(
        item
        for item in client.get("/api/conversations").json()["conversations"]
        if item["id"] == conversation_id
    )
    assert summary["course_ids"] == ["COURSE-1"]


def test_query_persists_provider_citations_and_ranked_evidence(seeded_database) -> None:
    client, _database, nvidia, ollama = make_client(seeded_database)
    response = client.post(
        "/textbooks/api/query",
        json={"question": "virtual memory", "provider": "auto", "source_ids": ["book-0"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["actual_provider"] == "nvidia"
    assert payload["fallback_used"] is False
    assert payload["citations"][0]["physical_page"] == 4
    assert payload["citations"][0]["citation_index"] == 1
    assert payload["citations"][0]["page_label"] == "P-0"
    assert payload["evidence"][0]["chunk_id"] == "chunk-0"
    assert nvidia.calls == 1 and ollama.calls == 0
    detail = client.get(f"/api/conversations/{payload['conversation_id']}").json()
    assistant = next(message for message in detail["messages"] if message["role"] == "assistant")
    assert assistant["actual_provider"] == "nvidia"
    assert assistant["evidence"][0]["citation_order"] == 1


def test_query_passes_selected_scope_ids_and_labels_to_provider(seeded_database) -> None:
    client, _database, nvidia, _ollama = make_client(seeded_database)

    response = client.post(
        "/api/query",
        json={
            "question": "virtual memory",
            "provider": "nvidia",
            "source_ids": ["book-0"],
            "course_ids": ["COURSE-1"],
        },
    )

    assert response.status_code == 200
    scope = nvidia.scopes[0]
    assert scope.sources == (("book-0", "Book 0"),)
    assert scope.courses == (("COURSE-1", "Course One"),)


def test_select_all_mode_reaches_provider_and_history(seeded_database) -> None:
    client, _database, nvidia, _ollama = make_client(seeded_database)

    response = client.post(
        "/api/query",
        json={
            "question": "Which principles apply?",
            "provider": "nvidia",
            "select_all_that_apply": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["select_all_that_apply"] is True
    assert nvidia.scopes[0].select_all_that_apply is True
    detail = client.get(f"/api/conversations/{payload['conversation_id']}").json()
    assert detail["messages"][0]["select_all_that_apply"] is True


def test_history_list_returns_filter_metadata(seeded_database) -> None:
    client, _database, _nvidia, _ollama = make_client(seeded_database)

    query = client.post(
        "/api/query",
        json={
            "question": "Which principles apply?",
            "provider": "nvidia",
            "course_ids": ["COURSE-1"],
            "select_all_that_apply": True,
        },
    )
    assert query.status_code == 200

    conversations = client.get("/api/conversations").json()["conversations"]
    assert len(conversations) == 1
    summary = conversations[0]
    assert summary["course_ids"] == ["COURSE-1"]
    assert summary["provider_choice"] == "nvidia"
    assert summary["actual_provider"] == "nvidia"
    assert summary["select_all_that_apply"] is True


def test_unfiltered_query_passes_full_effective_scope_to_provider(seeded_database) -> None:
    client, _database, nvidia, _ollama = make_client(seeded_database)

    response = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": "nvidia"},
    )

    assert response.status_code == 200
    scope = nvidia.scopes[0]
    assert scope.sources == (("book-0", "Book 0"), ("book-1", "Book 1"))
    assert scope.courses == (("COURSE-1", "Course One"),)


@pytest.mark.parametrize("provider", ["nvidia", "auto"])
def test_nvidia_query_survives_ollama_embedding_failure_with_fts(
    seeded_database, provider: str
) -> None:
    client, _database, nvidia, ollama = make_client(seeded_database)
    from textbook_rag.embeddings import EmbeddingError

    def fail(_texts):
        raise EmbeddingError("Ollama embedding request failed")

    client.app.state.runtime.retriever.embeddings.embed = fail
    response = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": provider, "source_ids": ["book-0"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["actual_provider"] == "nvidia"
    assert payload["retrieval_fallback_used"] is True
    assert payload["evidence"][0]["semantic_score"] is None
    assert payload["evidence"][0]["fts_score"] is not None
    assert nvidia.calls == 1 and ollama.calls == 0

    detail = client.get(f"/api/conversations/{payload['conversation_id']}").json()
    assert detail["messages"][1]["status"] == "ok"
    assert detail["messages"][1]["retrieval_fallback_used"] is True


def test_clear_all_requires_confirmation_and_preserves_index(seeded_database) -> None:
    client, database, _nvidia, _ollama = make_client(seeded_database)
    query = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": "nvidia", "source_ids": ["book-0"]},
    )
    assert query.status_code == 200
    assert client.delete("/api/conversations").status_code == 400
    cleared = client.delete("/api/conversations?confirm=true")
    assert cleared.json()["deleted_conversations"] == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2


def test_delete_one_and_unknown_conversation(seeded_database) -> None:
    client, _database, _nvidia, _ollama = make_client(seeded_database)
    query = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": "nvidia", "source_ids": ["book-0"]},
    ).json()
    assert client.delete(f"/api/conversations/{query['conversation_id']}").status_code == 204
    missing = client.get(f"/api/conversations/{query['conversation_id']}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_pdf_route_is_allowlisted_and_supports_ranges(seeded_database) -> None:
    client, _database, _nvidia, _ollama = make_client(seeded_database)
    ranged = client.get("/textbooks/api/sources/book-0/pdf", headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206
    assert ranged.content == b"%PDF"
    assert ranged.headers["accept-ranges"] == "bytes"
    assert client.get("/api/sources/../secret/pdf").status_code == 404
    assert client.get("/api/sources/not-configured/pdf").status_code == 404


def test_invalid_input_has_stable_error_shape(seeded_database) -> None:
    client, _database, _nvidia, _ollama = make_client(seeded_database)
    response = client.post("/api/query", json={"question": " ", "provider": "other"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


def test_retrieval_abstention_does_not_call_provider(seeded_database) -> None:
    client, _database, nvidia, ollama = make_client(seeded_database)
    response = client.post(
        "/api/query", json={"question": "cafeteria hours", "provider": "auto"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["actual_provider"] is None
    assert nvidia.calls == ollama.calls == 0


def test_history_evidence_snapshot_survives_source_reindex(seeded_database) -> None:
    client, database, _nvidia, _ollama = make_client(seeded_database)
    query = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": "nvidia", "source_ids": ["book-0"]},
    ).json()
    with database.transaction() as connection:
        connection.execute("DELETE FROM pages WHERE source_id='book-0'")
    detail = client.get(f"/api/conversations/{query['conversation_id']}").json()
    assistant = next(message for message in detail["messages"] if message["role"] == "assistant")
    assert assistant["evidence"][0]["chunk_id"] == "chunk-0"
    assert assistant["evidence"][0]["excerpt"].startswith("Virtual memory")


def test_provider_failure_persists_paired_assistant_turn(seeded_database) -> None:
    client, _database, nvidia, _ollama = make_client(seeded_database)
    from textbook_rag.providers import ProviderFailure

    def fail(_question, _evidence, _scope=None):
        nvidia.calls += 1
        raise ProviderFailure("nvidia", "timeout", "nvidia request timed out", retryable=True)

    nvidia.generate = fail
    response = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": "nvidia", "source_ids": ["book-0"]},
    )
    assert response.status_code == 503
    conversations = client.get("/api/conversations").json()["conversations"]
    detail = client.get(f"/api/conversations/{conversations[0]['id']}").json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["status"] == "provider_unavailable"


def test_retrieval_failure_persists_paired_assistant_turn(seeded_database) -> None:
    client, _database, nvidia, ollama = make_client(seeded_database)
    from textbook_rag.embeddings import EmbeddingError

    def fail(_texts):
        raise EmbeddingError("Ollama embedding request failed")

    client.app.state.runtime.retriever.embeddings.embed = fail
    response = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": "ollama", "source_ids": ["book-0"]},
    )
    assert response.status_code == 503
    conversation = client.get("/api/conversations").json()["conversations"][0]
    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["status"] == "retrieval_unavailable"
    assert nvidia.calls == ollama.calls == 0


def test_failed_auto_fallback_is_observable_in_error_and_history(seeded_database) -> None:
    client, _database, nvidia, ollama = make_client(seeded_database)
    from textbook_rag.providers import ProviderFailure

    def fail_nvidia(_question, _evidence, _scope=None):
        raise ProviderFailure("nvidia", "timeout", "nvidia timed out", retryable=True)

    def fail_ollama(_question, _evidence, _scope=None):
        raise ProviderFailure("ollama", "connection", "ollama offline", retryable=True)

    nvidia.generate = fail_nvidia
    ollama.generate = fail_ollama

    response = client.post(
        "/api/query",
        json={"question": "virtual memory", "provider": "auto", "source_ids": ["book-0"]},
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "provider_unavailable",
        "message": "ollama offline",
        "provider": "ollama",
        "kind": "connection",
        "fallback_used": True,
        "initial_failure_kind": "timeout",
    }
    conversation = client.get("/api/conversations").json()["conversations"][0]
    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    assistant = detail["messages"][1]
    assert assistant["status"] == "provider_unavailable"
    assert assistant["actual_provider"] == "ollama"
    assert assistant["fallback_used"] is True
    assert assistant["initial_failure_kind"] == "timeout"
