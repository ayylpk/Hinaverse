"""
memory_store.py —— ChromaDB 持久化记忆存储（共享模块）

load_memory 和 save_memory 共用同一个 Chroma 客户端和 collection，
避免重复初始化。需要用时直接导入 get_collection()。

用法:
    from agent_hina.memory_store import get_collection
    collection = get_collection()
"""
import os
import chromadb
import httpx
from pathlib import Path
from dotenv import load_dotenv
from chromadb import EmbeddingFunction

load_dotenv()

CHROMA_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"
CHROMA_PATH.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════
# 硅基流动 Embedding（BAAI/bge-m3）
# ═══════════════════════════════════════════════════

class SiliconFlowEmbedding(EmbeddingFunction):
    """硅基流动 bge-m3 Embedding API，国内服务器延迟低"""

    def __init__(self, api_key: str, model: str = "BAAI/bge-m3"):
        self.api_key = api_key
        self.model = model

    def __call__(self, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            "https://api.siliconflow.cn/v1/embeddings",
            json={
                "model": self.model,
                "input": texts,
                "encoding_format": "float",
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [d["embedding"] for d in sorted(data["data"], key=lambda x: x["index"])]


_embedding_fn = SiliconFlowEmbedding(
    api_key=os.getenv("SILICONFLOW_API_KEY", ""),
)

_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def get_collection():
    """获取或创建 hina_memories collection（懒加载，首次调用时创建）"""
    return _client.get_or_create_collection(
        name="hina_memories",
        embedding_function=_embedding_fn,  # type: ignore
    )

def get_all_documents():
    """返回所有记忆的文本列表，BM25 建索引用"""
    coll = get_collection()
    return coll.get(include=["documents"]).get("documents",[])

