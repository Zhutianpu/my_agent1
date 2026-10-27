"""memory_search：模型主动检索自己记忆的工具（对齐 CowAgent memory_search）。

数据源（MemoryStore）由装配间在启动时 bind 进来——工具类全局注册，
数据源按 agent 的 workspace 绑定。

SIMPLIFIED/P2 待办：bind 是类属性，多 agent 各绑各的会互相覆盖。
阶段 11 的 per-agent ToolManager 落地后改成实例级绑定。
"""

from ...common.log import logger
from .base_tool import BaseTool, ToolResult


class MemorySearchTool(BaseTool):
    name = "memory_search"
    description = (
        "检索你的长期记忆（MEMORY.md 和 memory/ 日记）。"
        "用户提到以前的事、你不确定的偏好或决定时，先查再答。"
    )
    params = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词"},
            "limit": {"type": "integer", "description": "最多返回几条（默认 5）", "default": 5},
        },
        "required": ["query"],
    }

    _store = None  # 装配间 bind 的 MemoryStore

    @classmethod
    def bind(cls, store):
        cls._store = store
        logger.debug("[Memory] memory_search 已绑定检索器")

    def execute(self, query: str, limit: int = 5) -> ToolResult:
        if self._store is None:
            return ToolResult.fail("error: 记忆系统未初始化")
        chunks = self._store.search(query, limit=limit)
        if not chunks:
            return ToolResult.success(f"（记忆里没有与「{query}」相关的内容）")
        parts = [f"找到 {len(chunks)} 条相关记忆："]
        for c in chunks:
            parts.append(f"\n--- {c.path} 第{c.start_line}-{c.end_line}行 ---\n{c.text}")
        return ToolResult.success("\n".join(parts))
