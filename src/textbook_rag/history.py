from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from uuid import uuid4

from .db import Database, utc_now
from .providers import ProviderChoice, ProviderFailure, ProviderOutcome
from .retrieval import Evidence


class HistoryNotFound(KeyError):
    pass


class HistoryStore:
    def __init__(self, database: Database):
        self.database = database

    def ensure_conversation(self, conversation_id: str | None, question: str) -> str:
        with self.database.transaction() as connection:
            if conversation_id:
                row = connection.execute(
                    "SELECT id FROM conversations WHERE id=?", (conversation_id,)
                ).fetchone()
                if not row:
                    raise HistoryNotFound(conversation_id)
                return conversation_id
            new_id = str(uuid4())
            title = question.strip().replace("\n", " ")[:80]
            connection.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (new_id, title, utc_now(), utc_now()),
            )
            return new_id

    def append_user(self, conversation_id: str, question: str, choice: ProviderChoice) -> str:
        message_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO messages(id, conversation_id, role, text, provider_choice, status) "
                "VALUES (?, ?, 'user', ?, ?, 'ok')",
                (message_id, conversation_id, question, choice),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id)
            )
        return message_id

    def append_assistant(
        self,
        conversation_id: str,
        *,
        text: str,
        choice: ProviderChoice,
        status: str,
        evidence: tuple[Evidence, ...],
        outcome: ProviderOutcome | None,
        failure: ProviderFailure | None = None,
    ) -> str:
        message_id = str(uuid4())
        citation_positions = (
            {
                chunk_id: index
                for index, chunk_id in enumerate(outcome.answer.cited_chunk_ids, 1)
            }
            if outcome
            else {}
        )
        if outcome:
            actual_provider = outcome.actual_provider
            fallback_used = outcome.fallback_used
            initial_failure_kind = outcome.initial_failure_kind
        elif failure:
            actual_provider = failure.provider
            fallback_used = failure.fallback_used
            initial_failure_kind = failure.initial_failure_kind
        else:
            actual_provider = None
            fallback_used = False
            initial_failure_kind = None
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO messages(id, conversation_id, role, text, provider_choice, actual_provider, "
                "fallback_used, initial_failure_kind, status) "
                "VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    conversation_id,
                    text,
                    choice,
                    actual_provider,
                    int(fallback_used),
                    initial_failure_kind,
                    status,
                ),
            )
            connection.executemany(
                "INSERT INTO message_evidence(message_id, chunk_id, source_id, source_title, physical_page, "
                "page_label, excerpt, rank, semantic_score, fts_score, fusion_score, citation_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        message_id,
                        item.chunk_id,
                        item.source_id,
                        item.source_title,
                        item.physical_page,
                        item.page_label,
                        item.excerpt,
                        item.rank,
                        item.semantic_score,
                        item.fts_score,
                        item.fusion_score,
                        citation_positions.get(item.chunk_id),
                    )
                    for item in evidence
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id)
            )
        return message_id

    def list(self) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS message_count "
                "FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id "
                "GROUP BY c.id ORDER BY c.updated_at DESC, c.id"
            ).fetchall()
        return [dict(row) for row in rows]

    def detail(self, conversation_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if not conversation:
                raise HistoryNotFound(conversation_id)
            messages = connection.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at, rowid",
                (conversation_id,),
            ).fetchall()
            result_messages = []
            for message in messages:
                evidence = connection.execute(
                    "SELECT chunk_id, source_id, source_title, physical_page, page_label, excerpt, rank, "
                    "semantic_score, fts_score, fusion_score, citation_order FROM message_evidence "
                    "WHERE message_id=? ORDER BY rank",
                    (message["id"],),
                ).fetchall()
                item = dict(message)
                item["fallback_used"] = bool(item["fallback_used"])
                item["evidence"] = [dict(row) for row in evidence]
                result_messages.append(item)
        result = dict(conversation)
        result["messages"] = result_messages
        return result

    def delete(self, conversation_id: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
            return cursor.rowcount > 0

    def clear(self) -> int:
        with self.database.transaction() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0])
            connection.execute("DELETE FROM conversations")
            return count
