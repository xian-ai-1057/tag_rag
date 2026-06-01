"""Re-export of history contracts schema (single source of truth)."""
import importlib.util
from pathlib import Path

_contract_path = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "103-chat-history-persistence"
    / "contracts"
    / "history_schema.py"
)
_spec = importlib.util.spec_from_file_location("history_contract", _contract_path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

Conversation = _module.Conversation
Message = _module.Message
StoredCitation = _module.StoredCitation
MessageRole = _module.MessageRole

__all__ = ["Conversation", "Message", "StoredCitation", "MessageRole"]
