"""SQLite-backed HistoryStore for chat history persistence."""
import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from src.history.models import Conversation, Message, MessageRole, StoredCitation

log = logging.getLogger("src.history")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conv_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_dt(value: str) -> datetime:
    # Strip trailing Z for broad Python compat, then attach UTC
    return datetime.fromisoformat(value.rstrip("Z")).replace(tzinfo=timezone.utc)


def _truncate_snapshot(text: str) -> str:
    if len(text) > 1000:
        return text[:999] + "…"
    return text


class HistoryStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from src.config import settings
            db_path = settings.history_db_path
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.executescript(_SCHEMA_SQL)

    def create_conversation(self, title: str | None = None) -> Conversation:
        conv_id = str(uuid.uuid4())
        created_at = _now_iso()
        stored_title = title if title is not None else ""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at) VALUES (?, ?, ?)",
                (conv_id, stored_title, created_at),
            )
        return Conversation(id=conv_id, title=stored_title, created_at=_parse_dt(created_at))

    def add_message(
        self,
        conv_id: str,
        role: MessageRole | str,
        content: str,
        citations: list[StoredCitation] | None = None,
    ) -> Message:
        # Store is the single truncate point (Lead arbitration #1)
        truncated_citations = [
            c.model_copy(update={"snapshot_text": _truncate_snapshot(c.snapshot_text)})
            for c in (citations or [])
        ]
        citations_json = json.dumps(
            [c.model_dump() for c in truncated_citations],
            ensure_ascii=False,
        )
        created_at = _now_iso()
        role_str = str(role)
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (conv_id, role, content, citations_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (conv_id, role_str, content, citations_json, created_at),
            )
            msg_id = cursor.lastrowid
        return Message(
            id=msg_id,
            conv_id=conv_id,
            role=MessageRole(role_str),
            content=content,
            citations=truncated_citations,
            created_at=_parse_dt(created_at),
        )

    def list_conversations(self) -> list[Conversation]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at FROM conversations ORDER BY created_at DESC"
            ).fetchall()
        return [
            Conversation(id=r[0], title=r[1], created_at=_parse_dt(r[2]))
            for r in rows
        ]

    def load_conversation(self, conv_id: str) -> tuple[Conversation, list[Message]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, title, created_at FROM conversations WHERE id = ?",
                (conv_id,),
            ).fetchone()
            if row is None:
                raise KeyError(conv_id)
            conv = Conversation(id=row[0], title=row[1], created_at=_parse_dt(row[2]))
            msg_rows = conn.execute(
                "SELECT id, conv_id, role, content, citations_json, created_at"
                " FROM messages WHERE conv_id = ? ORDER BY id ASC",
                (conv_id,),
            ).fetchall()
        messages = [
            Message(
                id=r[0],
                conv_id=r[1],
                role=MessageRole(r[2]),
                content=r[3],
                citations=[StoredCitation.model_validate(c) for c in json.loads(r[4])],
                created_at=_parse_dt(r[5]),
            )
            for r in msg_rows
        ]
        return conv, messages

    def delete_conversation(self, conv_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

    def rename_conversation(self, conv_id: str, new_title: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (new_title, conv_id),
            )
