"""CLI: ask a question against the RAG store."""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag import RAG


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: python scripts/ask.py "your question"', file=sys.stderr)
        return 2

    question = argv[1]
    rag = RAG()
    result = rag.query(question)

    print("Answer:")
    print(result.clean_answer)
    print()
    if not result.citations:
        print("(no citations)")
        return 0
    print("References:")
    for c in result.citations:
        src = Path(c.source_path).name if c.source_path else (c.doc_title or c.doc_id)
        page_str = f"page {c.page}" if c.page is not None else "page ?"
        char_range = f"char[{c.char_start}:{c.char_end}]" if c.char_start is not None else ""
        snippet = c.sentence_text[:200] + ("..." if len(c.sentence_text) > 200 else "")
        print(f"  [{c.ref_num}] {c.claim_text}")
        print(f"      ← {src}:{page_str} {char_range}")
        print(f"        \"{snippet}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
