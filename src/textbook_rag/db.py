from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from typing import Iterator

from .catalog import Catalog


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self, catalog: Catalog) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(schema)
            self._migrate_message_evidence_cascade(connection)
            self._migrate_message_evidence_snapshots(connection)
            self._migrate_message_initial_failure(connection)
            configured_source_ids = tuple(source.id for source in catalog.sources)
            placeholders = ",".join("?" for _ in configured_source_ids)
            connection.execute(
                f"UPDATE sources SET status='retired' WHERE id NOT IN ({placeholders})",
                configured_source_ids,
            )
            connection.executemany(
                "INSERT INTO courses(id, name) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                ((course.id, course.name) for course in catalog.courses),
            )
            for source in catalog.sources:
                connection.execute(
                    "INSERT INTO sources(id, title, file_name) VALUES (?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET title=excluded.title, file_name=excluded.file_name",
                    (source.id, source.title, source.file_name),
                )
                connection.execute("DELETE FROM source_courses WHERE source_id = ?", (source.id,))
                connection.executemany(
                    "INSERT INTO source_courses(source_id, course_id) VALUES (?, ?)",
                    ((source.id, course_id) for course_id in source.course_ids),
                )

    @staticmethod
    def _migrate_message_evidence_cascade(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=2"
        ).fetchone():
            return
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN;
                CREATE TABLE message_evidence_v2 (
                  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                  chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
                  rank INTEGER NOT NULL,
                  semantic_score REAL,
                  fts_score REAL,
                  fusion_score REAL NOT NULL,
                  citation_order INTEGER,
                  PRIMARY KEY (message_id, chunk_id)
                );
                INSERT INTO message_evidence_v2
                  SELECT message_id, chunk_id, rank, semantic_score, fts_score, fusion_score, citation_order
                  FROM message_evidence;
                DROP TABLE message_evidence;
                ALTER TABLE message_evidence_v2 RENAME TO message_evidence;
                INSERT INTO schema_migrations(version) VALUES (2);
                COMMIT;
                """
            )
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _migrate_message_evidence_snapshots(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=3"
        ).fetchone():
            return
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN;
                CREATE TABLE message_evidence_v3 (
                  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                  chunk_id TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  source_title TEXT NOT NULL,
                  physical_page INTEGER NOT NULL,
                  page_label TEXT NOT NULL,
                  excerpt TEXT NOT NULL,
                  rank INTEGER NOT NULL,
                  semantic_score REAL,
                  fts_score REAL,
                  fusion_score REAL NOT NULL,
                  citation_order INTEGER,
                  PRIMARY KEY (message_id, chunk_id)
                );
                INSERT INTO message_evidence_v3(
                  message_id, chunk_id, source_id, source_title, physical_page, page_label, excerpt,
                  rank, semantic_score, fts_score, fusion_score, citation_order
                )
                SELECT me.message_id, me.chunk_id, c.source_id, s.title, c.physical_page, c.page_label,
                       c.content, me.rank, me.semantic_score, me.fts_score, me.fusion_score,
                       me.citation_order
                FROM message_evidence me
                JOIN chunks c ON c.id=me.chunk_id
                JOIN sources s ON s.id=c.source_id;
                DROP TABLE message_evidence;
                ALTER TABLE message_evidence_v3 RENAME TO message_evidence;
                INSERT INTO schema_migrations(version) VALUES (3);
                COMMIT;
                """
            )
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _migrate_message_initial_failure(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=4"
        ).fetchone():
            return
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "initial_failure_kind" not in columns:
            connection.execute("ALTER TABLE messages ADD COLUMN initial_failure_kind TEXT")
        connection.execute("INSERT INTO schema_migrations(version) VALUES (4)")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
