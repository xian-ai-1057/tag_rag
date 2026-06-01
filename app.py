"""Streamlit UI: sidebar + multi-format upload + chat history + quality eval."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.config import settings
from src.eval import QualityReport, SentenceSupport, EntityFlag, evaluate
from src.history import HistoryStore, Conversation, Message, MessageRole, StoredCitation
from src.ingest import ingest_paths
from src.loaders import SUPPORTED_EXTS
from src.rag_chain import query, RagAnswer
from src.retrieval import RetrievedChunk
from src.vectorstore import fetch_chunks_by_ids, list_sources

st.set_page_config(page_title="Tag RAG", layout="wide")

DATA_DIR = Path("data/docs")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# session_state init
# ---------------------------------------------------------------------------

def _init_session_state() -> None:
    if "current_conv_id" not in st.session_state:
        st.session_state.current_conv_id = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_rename" not in st.session_state:
        st.session_state.pending_rename = False
    if "history_store" not in st.session_state:
        st.session_state.history_store = HistoryStore(settings.history_db_path)
    if "rename_conv_id" not in st.session_state:
        st.session_state.rename_conv_id = None


def _store() -> HistoryStore:
    return st.session_state.history_store


# ---------------------------------------------------------------------------
# conversation helpers
# ---------------------------------------------------------------------------

def _switch_conversation(conv_id: str) -> None:
    store = _store()
    conv, msgs = store.load_conversation(conv_id)
    st.session_state.current_conv_id = conv_id
    st.session_state.pending_rename = False
    st.session_state.messages = [
        {
            "role": m.role.value,
            "content": m.content,
            "citations": m.citations,
        }
        for m in msgs
    ]


def _new_conversation() -> None:
    store = _store()
    conv = store.create_conversation(title="")
    st.session_state.current_conv_id = conv.id
    st.session_state.messages = []
    st.session_state.pending_rename = True


def _delete_conversation(conv_id: str) -> None:
    store = _store()
    store.delete_conversation(conv_id)
    if st.session_state.current_conv_id == conv_id:
        st.session_state.current_conv_id = None
        st.session_state.messages = []
        st.session_state.pending_rename = False


# ---------------------------------------------------------------------------
# render helpers
# ---------------------------------------------------------------------------

def _format_source(s: str) -> str:
    if "#" in s:
        base, sheet = s.split("#", 1)
        return f"{base} → {sheet}"
    return s


def render_citations(citations: list) -> None:
    if not citations:
        st.caption("（本次回答未引用任何 source）")
        return
    context_ids = [c.context_id for c in citations]
    live = fetch_chunks_by_ids(context_ids)
    with st.expander(f"📚 引用來源（{len(citations)} 筆）", expanded=False):
        for c in citations:
            entry = live.get(c.context_id, {})
            md = entry.get("metadata") or {}
            # RetrievedChunk has .content; StoredCitation has .snapshot_text
            fallback_text = getattr(c, "content", None) or getattr(c, "snapshot_text", "")
            text = entry.get("text") or fallback_text
            filename = md.get("filename") or getattr(c, "filename", "?")
            page = int(md.get("page") or getattr(c, "page", 0) or 0)
            chunk_index = int(md.get("chunk_index") or getattr(c, "chunk_index", 0) or 0)
            display_n = getattr(c, "n", None) or getattr(c, "display_n", "?")
            score = getattr(c, "score", 0.0)
            stale = c.context_id not in live
            stale_tag = " · ⚠️ 文件已更新或被刪除（顯示為快照）" if stale else ""
            st.markdown(
                f"**[{display_n}]** `{_format_source(filename)}` · 第 {page} 頁 · "
                f"第 {chunk_index} 段 · score={score:.3f}"
                f" · `id={c.context_id}`{stale_tag}"
            )
            preview = text[:500] + ("…" if len(text) > 500 else "")
            st.code(preview, language=None)
            st.divider()


def render_quality_report(report: QualityReport) -> None:
    score = report.quality_score
    if score >= 0.8:
        color_icon = "🟢"
        color_label = "green"
    elif score >= 0.5:
        color_icon = "🟡"
        color_label = "orange"
    else:
        color_icon = "🔴"
        color_label = "red"

    with st.expander(f"🔍 品質檢查 {color_icon} score={score:.2f}", expanded=False):
        st.markdown(f"**品質分數：** :{color_label}[{score:.2f}]")

        if report.sentence_supports:
            st.markdown("**逐句支持：**")
            for ss in report.sentence_supports:
                icon = "✓" if ss.supported else "✗"
                overlap = f"overlap={ss.overlap_score:.2f}"
                chunk_hint = f" `{ss.best_match_context_id}`" if ss.best_match_context_id else ""
                st.markdown(f"- {icon} {ss.sentence} · {overlap}{chunk_hint}")

        if report.unsupported_entities:
            st.markdown(
                f"**⚠️ 偵測到 {len(report.unsupported_entities)} 個可能 hallucination 實體：**"
            )
            for ef in report.unsupported_entities:
                st.markdown(f"- :red[{ef.entity}] ({ef.kind}) — {ef.reason}")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    store = _store()
    with st.sidebar:
        st.title("📚 Tag RAG")

        if st.button("＋ 新對話", use_container_width=True, type="primary"):
            _new_conversation()
            st.rerun()

        st.subheader("對話記錄")
        convs = store.list_conversations()
        if not convs:
            st.caption("尚無對話，請點上方「＋ 新對話」")
        else:
            for conv in convs:
                is_current = conv.id == st.session_state.current_conv_id
                label = conv.title if conv.title else "（未命名對話）"
                date_str = conv.created_at.strftime("%m/%d")
                display_label = f"{'▶ ' if is_current else ''}{label} · {date_str}"

                col_btn, col_rename, col_del = st.columns([6, 1, 1])
                with col_btn:
                    if st.button(display_label, key=f"conv_{conv.id}", use_container_width=True):
                        _switch_conversation(conv.id)
                        st.session_state.rename_conv_id = None
                        st.rerun()
                with col_rename:
                    if st.button("✏️", key=f"rename_{conv.id}"):
                        st.session_state.rename_conv_id = conv.id
                        st.rerun()
                with col_del:
                    if st.button("🗑️", key=f"del_{conv.id}"):
                        _delete_conversation(conv.id)
                        st.session_state.rename_conv_id = None
                        st.rerun()

                if st.session_state.rename_conv_id == conv.id:
                    new_title = st.text_input(
                        "新標題",
                        value=conv.title,
                        key=f"rename_input_{conv.id}",
                        label_visibility="collapsed",
                    )
                    if st.button("確認", key=f"rename_confirm_{conv.id}"):
                        store.rename_conversation(conv.id, new_title)
                        st.session_state.rename_conv_id = None
                        st.rerun()

        st.divider()
        st.subheader("📂 已入庫文件")
        sources = list_sources()
        if not sources:
            st.caption("尚未入庫任何文件。")
        else:
            for s in sources:
                st.write(f"• {_format_source(s)}")


# ---------------------------------------------------------------------------
# Doc tab
# ---------------------------------------------------------------------------

def render_doc_tab() -> None:
    st.subheader("上傳文件")
    ext_types = [s.lstrip(".") for s in SUPPORTED_EXTS]
    files = st.file_uploader(
        f"支援格式：{', '.join('.' + e for e in ext_types)}",
        accept_multiple_files=True,
        type=ext_types,
    )
    if files and st.button("入庫", type="primary"):
        saved: list[str] = []
        for f in files:
            dest = DATA_DIR / f.name
            dest.write_bytes(f.getbuffer())
            saved.append(str(dest))
        with st.spinner("Ingesting…"):
            n = ingest_paths(saved)
        st.success(f"已入庫 {n} 個 chunks（來自 {len(saved)} 個檔案）")

    st.divider()
    st.subheader("已入庫文件")
    sources = list_sources()
    if not sources:
        st.info("尚未有文件，請先在上方上傳。")
    else:
        for s in sources:
            st.write(f"• {_format_source(s)}")


# ---------------------------------------------------------------------------
# Chat tab
# ---------------------------------------------------------------------------

def render_chat_tab() -> None:
    if st.session_state.current_conv_id is None:
        st.info("請從左側選擇或新增對話開始。")
        return

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                cites = m.get("citations") or []
                render_citations(cites)

    if q := st.chat_input("問點什麼…"):
        store = _store()
        conv_id = st.session_state.current_conv_id

        # user message
        store.add_message(conv_id, MessageRole.USER, q)
        st.session_state.messages.append({"role": "user", "content": q, "citations": []})
        with st.chat_message("user"):
            st.markdown(q)

        # query + eval
        with st.chat_message("assistant"):
            with st.spinner("檢索中…"):
                ans = query(q)
            st.markdown(ans.answer)
            render_citations(ans.citations)
            if ans.retrieved:
                report = evaluate(ans)
                render_quality_report(report)

        # persist assistant message
        stored_citations = [
            StoredCitation(
                context_id=c.context_id,
                display_n=c.n,
                score=c.score,
                snapshot_text=c.content,
            )
            for c in ans.citations
        ]
        store.add_message(conv_id, MessageRole.ASSISTANT, ans.answer, citations=stored_citations)
        st.session_state.messages.append({
            "role": "assistant",
            "content": ans.answer,
            "citations": ans.citations,
        })

        # auto rename on first message
        if st.session_state.pending_rename:
            store.rename_conversation(conv_id, q[:30])
            st.session_state.pending_rename = False

        st.rerun()


# ---------------------------------------------------------------------------
# App bootstrap — auto-load most recent conversation
# ---------------------------------------------------------------------------

def _maybe_load_recent_conversation() -> None:
    if st.session_state.current_conv_id is not None:
        return
    store = _store()
    convs = store.list_conversations()
    if convs:
        _switch_conversation(convs[0].id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_init_session_state()
_maybe_load_recent_conversation()

render_sidebar()

st.title("📚 Tag RAG — Citation Demo")
st.caption("本地 Ollama + ChromaDB + 段落級引用 | 多格式 | 對話歷史 | 品質評估")

tab_docs, tab_chat = st.tabs(["📥 文件管理", "💬 問答"])

with tab_docs:
    render_doc_tab()

with tab_chat:
    render_chat_tab()
