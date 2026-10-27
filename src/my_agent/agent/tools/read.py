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
        p = Path(path).expanduser()
        if p.is_dir():
            return ToolResult.fail(f"error: {path} 是目录不是文件（列目录请用 ls）")
        if not p.is_file():
            # 报出解析后的绝对路径：模型能看到自己相对路径解析到了哪，自我纠正
            return ToolResult.fail(f"error: 文件不存在: {path}（已解析为 {p.absolute()}）")
        text = _read_text_best_effort(p)
        lines = text.splitlines()
        total = len(lines)
        chunk = lines[offset - 1: offset - 1 + limit]
        text = "\n".join(chunk)
        max_chars = conf().get("tool_result_max_chars", 6000)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...（已截断，共 {total} 行，本次返回第 {offset}~{offset + len(chunk) - 1} 行）"
        return ToolResult.success(text if text else "（空文件）")


def _read_text_best_effort(p: Path) -> str:
    """Windows 真机教训：中文环境里很多文件是 GBK 存的（echo/记事本默认），
    硬按 utf-8 + errors=replace 读出来全是乱码等于"读不到"。
    按 utf-8-sig（兼容 BOM）→ gbk 顺序试，都失败才退回 replace。"""
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
