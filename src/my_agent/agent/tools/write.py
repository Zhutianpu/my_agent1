"""write_file：写文件（整个覆盖）。自动创建父目录。"""

from pathlib import Path

from .base_tool import BaseTool, ToolResult


class WriteFileTool(BaseTool):
    name = "write_file"
    risk = "write"  # 覆盖式写文件，首次执行问用户
    description = "把内容写入指定文件（整文件覆盖，父目录不存在会自动创建）。"
    params = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的完整内容"},
        },
        "required": ["path", "content"],
    }

    def execute(self, path: str, content: str) -> ToolResult:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult.success(f"ok: 已写入 {path}（{len(content)} 字符）")
