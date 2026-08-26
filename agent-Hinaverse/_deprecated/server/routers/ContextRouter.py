"""
/context/upload —— 文件上下文 & 记忆上传
"""
import time as time_module
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Request, Form, UploadFile, File

router = APIRouter(prefix="/context", tags=["文件上下文"])


# ═══════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════

def _extract_text(file: UploadFile) -> str:
    """从上传的文件中提取文本"""
    filename = (file.filename or "").lower()
    content = file.file.read()

    # txt / md
    if filename.endswith((".txt", ".md")):
        return content.decode("utf-8", errors="replace")

    # pdf
    if filename.endswith(".pdf"):
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(BytesIO(content))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            return "[错误] 服务端未安装 PyPDF2"

    # docx
    if filename.endswith(".docx"):
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return "[错误] 服务端未安装 python-docx"

    # 其他 → 尝试按 UTF-8 读
    return content.decode("utf-8", errors="replace")


def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """简单按段落分块，每块不超过 chunk_size 字"""
    chunks = []
    current = ""
    for para in text.split("\n"):
        if len(current) + len(para) > chunk_size and current:
            chunks.append(current.strip())
            current = para
        else:
            current += "\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ═══════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════

@router.post("/upload")
async def upload_context(
    request: Request,
    type: str = Form(...),
    file: UploadFile = File(...),
):
    """接收文件作为上下文（file）或记忆（memory）"""
    graph = request.app.state.hina_graph
    text = _extract_text(file)
    session_id = request.headers.get("X-Session-Id", "default")

    if type == "file":
        # 作为上下文 → 调 agent 处理
        config = {"configurable": {"thread_id": session_id}}
        try:
            from langchain_core.messages import HumanMessage
            state_input = {
                "messages": [HumanMessage(content=f"[用户上传了文件 {file.filename}]\n\n{text}")],
            }
            result = await graph.ainvoke(state_input, config)
            reply = result["messages"][-1].content if result.get("messages") else "已收到文件"
            mood = result.get("mood", "普通")
            status = result.get("status", "在线")

            # 存 Chroma
            try:
                from agent_hina.memory_store import get_collection
                coll = get_collection()
                coll.add(
                    ids=[f"file-{session_id}-{int(time_module.time())}"],
                    documents=[text],
                    metadatas=[{
                        "timestamp": datetime.now().isoformat(),
                        "memory_type": "file_context",
                        "session_id": session_id,
                        "filename": file.filename or "unknown",
                    }],
                )
            except Exception as e:
                print(f"  [context] Chroma 写入失败: {e}")

            return {
                "code": 200,
                "message": "success",
                "data": {"reply": reply, "mood": mood, "status": status},
            }
        except Exception as e:
            print(f"  [context] agent 调用失败: {e}")
            return {"code": 500, "message": str(e), "data": None}

    elif type == "memory":
        # 作为记忆 → 分块 + 向量化 + Chroma
        chunks = _chunk_text(text)
        try:
            from agent_hina.memory_store import get_collection
            coll = get_collection()
            for i, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                coll.add(
                    ids=[f"doc-{session_id}-{int(time_module.time())}-{i}"],
                    documents=[chunk],
                    metadatas=[{
                        "timestamp": datetime.now().isoformat(),
                        "memory_type": "document",
                        "session_id": session_id,
                        "filename": file.filename or "unknown",
                        "chunk_index": i,
                    }],
                )
            print(f"  [context] 记忆上传: {len(chunks)} 块, session={session_id}")
            return {"code": 200, "message": f"已存储 {len(chunks)} 个记忆片段", "data": None}
        except Exception as e:
            print(f"  [context] Chroma 写入失败: {e}")
            return {"code": 500, "message": str(e), "data": None}

    else:
        return {"code": 400, "message": f"未知 type: {type}", "data": None}
