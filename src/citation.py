"""renumber_and_filter() — reindexes inline [n] markers by first-appearance order."""
import logging
import re

from src.retrieval import RetrievedChunk
from src.utils import CITE_RE

log = logging.getLogger("rag")

_MULTI_SPACE_RE = re.compile(r" {2,}")


def renumber_and_filter(
    answer: str, retrieved: list[RetrievedChunk]
) -> tuple[str, list[RetrievedChunk]]:
    """依「答案中首次出現的順序」重編號 inline [n]，並刪除編造/未引用的 marker。

    範例：
      retrieved n = [1,2,3,4,5]
      LLM 原答：'句A [2]. 句B [4][2][99].'
      seen_order = [2, 4]（99 不在範圍）
      remap = {2: 1, 4: 2}
      新答：'句A [1]. 句B [2][1].'
      citations = [chunk(原 n=2, 新 n=1), chunk(原 n=4, 新 n=2)]
    """
    valid_ns = {c.n for c in retrieved}
    seen_order: list[int] = []
    fabricated: set[int] = set()
    for m in CITE_RE.finditer(answer):
        n = int(m.group(1))
        if n in valid_ns:
            if n not in seen_order:
                seen_order.append(n)
        else:
            fabricated.add(n)

    remap = {old: new for new, old in enumerate(seen_order, start=1)}

    def _sub(m: re.Match[str]) -> str:
        n = int(m.group(1))
        return f"[{remap[n]}]" if n in remap else ""

    new_answer = CITE_RE.sub(_sub, answer)
    new_answer = _MULTI_SPACE_RE.sub(" ", new_answer)

    chunk_by_old_n = {c.n: c for c in retrieved}
    new_citations = [
        chunk_by_old_n[old].model_copy(update={"n": new})
        for old, new in sorted(remap.items(), key=lambda x: x[1])
    ]

    log.info("[renumber] LLM cited (in order): %s; fabricated: %s",
             seen_order, sorted(fabricated) if fabricated else "—")
    log.info("[renumber] remap (old → new): %s", remap)
    return new_answer, new_citations
