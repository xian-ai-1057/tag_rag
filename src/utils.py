"""Cross-module helpers shared by the pipeline: inline [n] citation regex + log preview."""
import re

CITE_RE = re.compile(r"\[(\d+)\]")


def preview(text: str, n: int = 80) -> str:
    t = text.replace("\n", "⏎ ").strip()
    return t if len(t) <= n else t[:n] + "…"
