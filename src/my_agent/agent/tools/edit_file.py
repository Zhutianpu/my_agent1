"""edit_file：精确替换文件里的一段文字（对齐 CowAgent 的 edit 工具）。

契约：old_text 必须在文件里**唯一出现一次**——0 次是"没找到"，
多次是"定位不准"，都要求调用方给更长的上下文。宁可失败也不瞎改。
"""

from pathlib import Path

from .base_tool import BaseTool, ToolResult


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "精确替换文件中的一段文字：把 old_text 替换为 new_text。"
        "old_text 必须在文件中唯一出现一次，适合小改动（比 write_file 整文件覆盖安全）。"
    )
    params = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_text": {"type": "string", "description": "要被替换掉的原文（须唯一出现一次）"},
            "new_text": {"type": "string", "description": "替换成的新内容"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def execute(self, path: str, old_text: str, new_text: str) -> ToolResult:
        p = Path(path)
        if not p.exists():
            return ToolResult.fail(f"error: 文件不存在: {path}")
        content = p.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count == 0:
            return ToolResult.fail("error: old_text 在文件中没找到（先用 read_file 确认原文）")
        if count > 1:
            return ToolResult.fail(
                f"error: old_text 出现了 {count} 次，定位不唯一，请带上更长的上下文再试")
        p.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return ToolResult.success(f"ok: 已替换 {path} 中 1 处（{len(old_text)} → {len(new_text)} 字符）")
