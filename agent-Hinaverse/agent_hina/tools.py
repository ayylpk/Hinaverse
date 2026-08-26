from langchain.tools import tool
from langchain_tavily import TavilySearch
from agent_hina.models import chat_model, load_memory_model
import os
from typing import Literal


@tool
def search_web(query: str) -> str:
    """搜互联网，拿实时信息。query 是搜索词。"""
    try:
        search = TavilySearch(
            max_results=3,
            api_key=os.getenv("TAVILY_API_KEY"),
        )
        result = search.invoke(query)
        return str(result)
    except Exception as e:
        return f"搜索失败: {e}"


tools = [search_web]
tools_by_name = {t.name: t for t in tools}
model_with_tools = chat_model.bind_tools(tools)
