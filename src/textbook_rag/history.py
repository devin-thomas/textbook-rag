from __future__ import annotations

from dataclasses import dataclass
import json
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

    @staticmethod
    def _decode_course_ids(value: object) -> list[str]:
        if not isinstance(value, str):
            return []
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(decoded, list):
            return []
        return [item for item in decoded if isinstance(item, str)]

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

    def append_user(
        self,
        conversation_id: str,
        question: str,
        choice: ProviderChoice,
        *,
        course_ids: tuple[str, ...] = (),
        select_all_that_apply: bool = False,
    ) -> str:
        message_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO messages(id, conversation_id, role, text, provider_choice, select_all_that_apply, status) "
                "VALUES (?, ?, 'user', ?, ?, ?, 'ok')",
                (message_id, conversation_id, question, choice, int(select_all_that_apply)),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=?, course_ids=? WHERE id=?",
                (utc_now(), json.dumps(list(dict.fromkeys(course_ids))), conversation_id),
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
        retrieval_fallback_used: bool = False,
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
                "fallback_used, retrieval_fallback_used, initial_failure_kind, status) "
                "VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    conversation_id,
                    text,
                    choice,
                    actual_provider,
                    int(fallback_used),
                    int(retrieval_fallback_used),
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
                "SELECT c.id, c.title, c.course_ids, c.created_at, c.updated_at, "
                "COUNT(m.id) AS message_count, "
                "(SELECT latest_user.provider_choice FROM messages latest_user "
                " WHERE latest_user.conversation_id=c.id AND latest_user.role='user' "
                " ORDER BY latest_user.created_at DESC, latest_user.rowid DESC LIMIT 1) AS provider_choice, "
                "(SELECT latest_assistant.actual_provider FROM messages latest_assistant "
                " WHERE latest_assistant.conversation_id=c.id AND latest_assistant.role='assistant' "
                " ORDER BY latest_assistant.created_at DESC, latest_assistant.rowid DESC LIMIT 1) AS actual_provider, "
                "(SELECT latest_mode.select_all_that_apply FROM messages latest_mode "
                " WHERE latest_mode.conversation_id=c.id AND latest_mode.role='user' "
                " ORDER BY latest_mode.created_at DESC, latest_mode.rowid DESC LIMIT 1) AS select_all_that_apply "
                "FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id "
                "GROUP BY c.id ORDER BY c.updated_at DESC, c.id"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["course_ids"] = self._decode_course_ids(item.get("course_ids"))
            item["select_all_that_apply"] = bool(item.get("select_all_that_apply"))
            result.append(item)
        return result

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
                item["retrieval_fallback_used"] = bool(item["retrieval_fallback_used"])
                item["select_all_that_apply"] = bool(item["select_all_that_apply"])
                item["evidence"] = [dict(row) for row in evidence]
                result_messages.append(item)
        result = dict(conversation)
        result["course_ids"] = self._decode_course_ids(result.get("course_ids"))
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
