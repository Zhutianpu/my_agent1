"""Prompt 编译包：workspace 管理 + system prompt 分段编译。

对齐 CowAgent agent/prompt/：
  workspace.py —— agent 的家：ensure_workspace 造目录与模板，load_context_files 读文件
  builder.py   —— 编译器：原料进（工具/文件/运行时信息）→ system prompt 字符串出
"""

from .builder import ContextFile, build_system_prompt
from .workspace import ensure_workspace, load_context_files

__all__ = [
    "ContextFile",
    "build_system_prompt",
    "ensure_workspace",
    "load_context_files",
]
