"""search_files：在目录里按正则搜文件内容（简化版 grep）。

防护：跳过 .git/二进制/大文件，命中数封顶——搜索结果也是要进上下文的。
"""

import re
from pathlib import Path

from .base_tool import BaseTool, ToolResult

_MAX_HITS = 50
_MAX_FILE_BYTES = 1024 * 1024
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "在指定目录下按正则表达式搜索文件内容，返回 文件:行号:内容 的命中列表。"
    params = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {"type": "string", "description": "搜索的目录", "default": "."},
        },
        "required": ["pattern"],
    }

    def execute(self, pattern: str, path: str = ".") -> ToolResult:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return ToolResult.fail(f"error: 正则不合法: {e}")
        root = Path(path)
        if not root.is_dir():
            return ToolResult.fail(f"error: 目录不存在: {path}")
        hits = []
        for f in sorted(root.rglob("*")):
            if len(hits) >= _MAX_HITS:
                break
            if not f.is_file() or f.stat().st_size > _MAX_FILE_BYTES:
                continue
            if _SKIP_DIRS & set(f.parts):
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{f}:{i}: {line.strip()[:150]}")
                        if len(hits) >= _MAX_HITS:
                            break
            except OSError:
                continue
        if not hits:
            return ToolResult.success("（无命中）")
        suffix = f"\n...（已达 {_MAX_HITS} 条上限）" if len(hits) >= _MAX_HITS else ""
        return ToolResult.success("\n".join(hits) + suffix)
