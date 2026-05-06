"""CLI: ingest documents into the RAG store."""
from __future__ import annotations
import sys
from pathlib import Path

# Allow running from project root: add it to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag import RAG


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python scripts/ingest.py <path1> [<path2> ...]", file=sys.stderr)
        return 2

    paths = argv[1:]
    rag = RAG()
    total = 0
    for p in paths:
        # ingest one at a time so per-file count is reportable
        n = rag.ingest([p])
        print(f"  {p}: {n} chunks")
        total += n
    print(f"Total: {total} chunks ingested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
