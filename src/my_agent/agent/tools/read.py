"""read_file：读文件内容。

防护：offset/limit 分页 + 总字符截断——模型的上下文是稀缺资源，
10 万行的文件直接塞进去等于自杀（对齐 CowAgent read 工具的思路）。
"""

from pathlib import Path

from ...config import conf
from .base_tool import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "读取指定文件的内容。大文件请用 offset/limit 分页读，不要一次全读。"
    params = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "offset": {"type": "integer", "description": "从第几行开始（默认 1）", "default": 1},
            "limit": {"type": "integer", "description": "最多读几行（默认 400）", "default": 400},
        },
        "required": ["path"],
    }

    def execute(self, path: str, offset: int = 1, limit: int = 400) -> ToolResult:
        p = Path(path)
        if not p.is_file():
            return ToolResult.fail(f"error: 文件不存在: {path}")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        chunk = lines[offset - 1: offset - 1 + limit]
        text = "\n".join(chunk)
        max_chars = conf().get("tool_result_max_chars", 6000)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...（已截断，共 {total} 行，本次返回第 {offset}~{offset + len(chunk) - 1} 行）"
        return ToolResult.success(text if text else "（空文件）")
