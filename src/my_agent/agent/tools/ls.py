"""ls：列目录。条目带上 [dir]/[file] 标记，模型一眼能分辨。"""

from pathlib import Path

from .base_tool import BaseTool, ToolResult

_MAX_ENTRIES = 200


class LsTool(BaseTool):
    name = "ls"
    description = "列出目录下的文件和子目录。"
    params = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "目录路径", "default": "."}},
    }

    def execute(self, path: str = ".") -> ToolResult:
        p = Path(path)
        if not p.is_dir():
            return ToolResult.fail(f"error: 目录不存在: {path}")
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
        lines = [f"[{'dir' if e.is_dir() else 'file'}] {e.name}" for e in entries[:_MAX_ENTRIES]]
        if len(entries) > _MAX_ENTRIES:
            lines.append(f"...（还有 {len(entries) - _MAX_ENTRIES} 项未显示）")
        return ToolResult.success("\n".join(lines) if lines else "（空目录）")
