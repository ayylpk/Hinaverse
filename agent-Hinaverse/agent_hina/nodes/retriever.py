"""
retriever.py —— 向量检索 (ChromaDB)

用法:
    from agent_hina.nodes.retriever import get_retriever

    retriever = get_retriever()
    docs, distances = retriever.retrieve("7月24号发生了什么", n=5)
"""

from agent_hina.memory_store import get_collection


class VectorRetriever:
    """ChromaDB 向量检索，单例模式"""

    def retrieve(self, query: str, n: int = 5) -> tuple[list[str], list[float]]:
        """返回 (文档列表, 距离列表)，Chroma 距离越小越相关"""
        coll = get_collection()
        results = coll.query(query_texts=[query], n_results=n, include=["documents", "distances"])
        if not results:
            return [], []
        docs: list[str] = results.get("documents") or [[]]  # type: ignore
        distances: list[float] = results.get("distances") or [[]]  # type: ignore
        return docs[0] if docs else [], distances[0] if distances else []


# ── 单例 ──

_retriever: VectorRetriever | None = None


def get_retriever() -> VectorRetriever:
    global _retriever
    if _retriever is None:
        _retriever = VectorRetriever()
    return _retriever
