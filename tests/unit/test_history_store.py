"""Unit tests for HistoryStore — Spec 103 AC coverage."""
import sqlite3
import threading
import time
import uuid

import pytest

from src.history.models import Conversation, Message, MessageRole, StoredCitation
from src.history.store import HistoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_citation(snapshot_text: str = "chunk text", display_n: int = 1) -> StoredCitation:
    return StoredCitation(
        context_id=f"ctx-{display_n}",
        display_n=display_n,
        score=0.75,
        snapshot_text=snapshot_text,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_conversation_returns_uuid_id(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite")
    conv = store.create_conversation(title="test conv")
    # Must be a valid UUID4 — uuid.UUID will raise if malformed
    parsed = uuid.UUID(conv.id, version=4)
    assert str(parsed) == conv.id
    assert conv.title == "test conv"


def test_add_message_persists(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite")
    conv = store.create_conversation(title="persist test")
    msg = store.add_message(conv.id, MessageRole.USER, "Hello world?")
    assert msg.id is not None
    assert msg.content == "Hello world?"
    assert msg.role == MessageRole.USER
    assert msg.citations == []

    _, messages = store.load_conversation(conv.id)
    assert len(messages) == 1
    assert messages[0].content == "Hello world?"
    assert messages[0].role == MessageRole.USER


def test_round_trip_after_reconnect(tmp_path):
    db = tmp_path / "shared.sqlite"
    store_a = HistoryStore(db)
    conv = store_a.create_conversation(title="shared conv")
    store_a.add_message(conv.id, MessageRole.USER, "question")
    store_a.add_message(
        conv.id,
        MessageRole.ASSISTANT,
        "answer [1]",
        citations=[_make_citation("some chunk text")],
    )

    # Fresh instance — simulates process restart
    store_b = HistoryStore(db)
    loaded_conv, loaded_msgs = store_b.load_conversation(conv.id)

    assert loaded_conv.title == "shared conv"
    assert loaded_conv.id == conv.id
    assert len(loaded_msgs) == 2
    assert loaded_msgs[0].content == "question"
    assert loaded_msgs[0].role == MessageRole.USER
    assert loaded_msgs[1].content == "answer [1]"
    assert loaded_msgs[1].role == MessageRole.ASSISTANT
    assert loaded_msgs[1].citations[0].context_id == "ctx-1"


def test_cascade_delete(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite")
    conv = store.create_conversation(title="to delete")
    for i in range(3):
        store.add_message(conv.id, MessageRole.USER, f"msg {i}")

    store.delete_conversation(conv.id)

    # Verify via raw SQL that messages are gone
    conn = sqlite3.connect(str(tmp_path / "h.sqlite"))
    conn.execute("PRAGMA foreign_keys = ON;")
    count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conv_id = ?", (conv.id,)
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_snapshot_text_truncation(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite")
    conv = store.create_conversation()
    long_text = "A" * 2000
    # Pass as raw StoredCitation — store must truncate before Pydantic validate
    citation = StoredCitation(
        context_id="ctx-1",
        display_n=1,
        score=0.5,
        snapshot_text="A" * 1000,  # valid length for construction
    )
    # Bypass model validation to simulate caller sending long text
    citation_raw = citation.model_copy(update={"snapshot_text": long_text})

    msg = store.add_message(conv.id, MessageRole.ASSISTANT, "reply", citations=[citation_raw])

    assert len(msg.citations[0].snapshot_text) <= 1000
    assert msg.citations[0].snapshot_text.endswith("…")

    # Verify persisted value too
    _, messages = store.load_conversation(conv.id)
    persisted_snap = messages[0].citations[0].snapshot_text
    assert len(persisted_snap) <= 1000
    assert persisted_snap.endswith("…")


def test_concurrent_writes_wal_mode(tmp_path):
    db = tmp_path / "concurrent.sqlite"
    store = HistoryStore(db)
    conv = store.create_conversation(title="concurrent test")

    errors = []

    def writer():
        s = HistoryStore(db)
        for _ in range(100):
            try:
                s.add_message(conv.id, MessageRole.USER, "concurrent msg")
            except Exception as e:
                errors.append(e)

    def reader():
        s = HistoryStore(db)
        for _ in range(100):
            try:
                s.list_conversations()
            except Exception as e:
                errors.append(e)

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=reader)
    start = time.monotonic()
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    elapsed = time.monotonic() - start

    assert errors == [], f"Concurrent errors: {errors}"
    assert elapsed < 5.0, f"Took too long: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Additional AC coverage
# ---------------------------------------------------------------------------

def test_delete_conversation_nonexistent_does_not_raise(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite")
    store.delete_conversation("00000000-0000-0000-0000-000000000000")  # must not raise


def test_rename_conversation_nonexistent_does_not_raise(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite")
    store.rename_conversation("00000000-0000-0000-0000-000000000000", "new title")


def test_load_conversation_nonexistent_raises_key_error(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite")
    with pytest.raises(KeyError):
        store.load_conversation("00000000-0000-0000-0000-000000000000")


def test_list_conversations_created_at_desc_order(tmp_path):
    store = HistoryStore(tmp_path / "h.sqlite")
    c1 = store.create_conversation(title="first")
    time.sleep(0.011)
    c2 = store.create_conversation(title="second")
    time.sleep(0.011)
    c3 = store.create_conversation(title="third")

    convs = store.list_conversations()
    assert convs[0].id == c3.id
    assert convs[1].id == c2.id
    assert convs[2].id == c1.id


def test_role_enum_persists_as_string(tmp_path):
    db = tmp_path / "h.sqlite"
    store = HistoryStore(db)
    conv = store.create_conversation()
    store.add_message(conv.id, MessageRole.ASSISTANT, "reply")

    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON;")
    role_val = conn.execute(
        "SELECT role FROM messages WHERE conv_id = ?", (conv.id,)
    ).fetchone()[0]
    conn.close()
    assert role_val == "assistant"


def test_wal_mode_enabled(tmp_path):
    db = tmp_path / "h.sqlite"
    HistoryStore(db)
    conn = sqlite3.connect(str(db))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_settings_history_db_path_default():
    from src.config import Settings
    assert Settings().history_db_path == "./data/history.sqlite"


def test_schema_fixtures_validate():
    import json
    from pathlib import Path

    fixtures_dir = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "103-chat-history-persistence"
        / "contracts"
        / "fixtures"
    )
    Conversation.model_validate(
        json.loads((fixtures_dir / "conversation_example.json").read_text())
    )
    Message.model_validate(
        json.loads((fixtures_dir / "message_example.json").read_text())
    )
    StoredCitation.model_validate(
        json.loads((fixtures_dir / "stored_citation_example.json").read_text())
    )
