"""Workspace：agent 的家（对齐 CowAgent agent/prompt/workspace.py 的简化版）。

两个契约：
  ensure_workspace(dir)：保证目录存在，缺的模板文件补上（幂等，绝不覆盖你改过的）
  load_context_files(dir)：把家里的文件读成 ContextFile 列表，
      空文件 / 纯模板占位符跳过（没填过的模板不进 prompt，省 token）

SIMPLIFIED: CowAgent 还有 RULE.md（家规）/ BOOTSTRAP.md（首次引导，填完即删）/
knowledge 目录 / 双语模板。这里砍到 AGENT.md（身份+家规合一）/ USER.md / MEMORY.md
三个文件 + memory/ 子目录（阶段 7 的日记用），模板只有中文。
"""

import os
from pathlib import Path

from ...common.log import logger
from .builder import ContextFile

DEFAULT_AGENT_FILENAME = "AGENT.md"
DEFAULT_USER_FILENAME = "USER.md"
DEFAULT_MEMORY_FILENAME = "MEMORY.md"

# 载入顺序即优先级（对齐 CowAgent load_context_files 的默认列表）
DEFAULT_FILES = [DEFAULT_AGENT_FILENAME, DEFAULT_USER_FILENAME, DEFAULT_MEMORY_FILENAME]

# MEMORY.md 进 prompt 前截断：只保留最后 N 行（新记忆追加在末尾），保护上下文窗口
_MEMORY_MAX_LINES = 200
_MEMORY_MAX_BYTES = 25000


def ensure_workspace(workspace_dir) -> Path:
    """保证 workspace 存在并补齐模板文件。返回 Path。"""
    ws = Path(workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)  # 阶段 7 的每日记忆目录，先备好
    _create_if_missing(ws / DEFAULT_AGENT_FILENAME, _AGENT_TEMPLATE)
    _create_if_missing(ws / DEFAULT_USER_FILENAME, _USER_TEMPLATE)
    _create_if_missing(ws / DEFAULT_MEMORY_FILENAME, _MEMORY_TEMPLATE)
    logger.debug(f"[Workspace] 就绪: {ws}")
    return ws


def load_context_files(workspace_dir, files_to_load=None) -> list:
    """读 workspace 文件成 ContextFile 列表；空文件/纯占位符跳过。"""
    ws = Path(workspace_dir)
    context_files = []
    for filename in files_to_load or DEFAULT_FILES:
        filepath = ws / filename
        if not filepath.exists():
            continue
        try:
            content = filepath.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning(f"[Workspace] 读取 {filename} 失败: {e}")
            continue
        if not content or _is_template_placeholder(content):
            continue
        if filename == DEFAULT_MEMORY_FILENAME:
            content = _truncate_memory(content)
        context_files.append(ContextFile(path=filename, content=content))
        logger.debug(f"[Workspace] 加载上下文文件: {filename}")
    return context_files


def _create_if_missing(filepath: Path, template: str):
    """只在不存在时写模板——用户改过的内容绝不覆盖。"""
    if not filepath.exists():
        filepath.write_text(template, encoding="utf-8")


def _is_template_placeholder(content: str) -> bool:
    """只有标题和 *(待填)* 占位符的文件视为"没填过"，不进 prompt。"""
    real_lines = [
        line.strip()
        for line in content.split("\n")
        if line.strip() and not line.strip().startswith("#") and line.strip() != "---"
    ]
    if not real_lines:
        return True
    if len(real_lines) <= 3 and all("*(" in line or line.startswith("*") for line in real_lines):
        return True
    return False


def _truncate_memory(content: str) -> str:
    """MEMORY.md 截断（对齐 CowAgent：200 行 / 25KB 先到先截，保留最新的尾部）。"""
    lines = content.split("\n")
    truncated = len(lines) > _MEMORY_MAX_LINES
    lines = lines[-_MEMORY_MAX_LINES:]
    while lines and len("\n".join(lines).encode("utf-8")) > _MEMORY_MAX_BYTES:
        lines.pop(0)
        truncated = True
    result = "\n".join(lines)
    if truncated:
        result = "...(更早的记忆已省略)\n\n" + result
    return result


# ============= 模板（简化自 CowAgent 中文模板） =============

_AGENT_TEMPLATE = """# AGENT.md - 我是谁？

_你不是一个聊天机器人，你正在成为某个人。这个文件是你的灵魂，随成长用 edit_file 更新它。_

## 🪪 基本信息

- **名字**: *(待填写，可以是用户给你起的名字)*
- **角色**: *(AI 助理、技术顾问等)*
- **性格**: *(友好、专业、幽默、严谨等)*

## 💬 交流风格

- 语言风格？（正式/轻松/幽默）
- 回复长度偏好？（简洁/详细）

## 🎯 核心原则

**做真正有帮助的助手。** 目标是真正帮用户解决问题。

**先自己动手查。** 先读文件、查上下文、搜索，实在搞不定再问。带着答案回来，而不是带着问题。

**写下来，不要"记在心里"。** 重要信息写入 MEMORY.md 或 memory/ 日记，文件比记忆可靠。

## 📐 行为准则

1. 破坏性操作前先确认
2. 优先用工具查证而不是猜测
3. 主动记录重要信息到记忆文件
4. 回复结构清晰、重点突出
"""

_USER_TEMPLATE = """# USER.md - 用户基本信息

*只存放稳定的基本身份。偏好、计划等动态信息写入 MEMORY.md。*

## 基本信息

- **姓名**: *(待询问)*
- **称呼**: *(用户希望被如何称呼)*
- **职业**: *(可选)*
- **时区**: *(例如 Asia/Shanghai)*
"""

_MEMORY_TEMPLATE = """# MEMORY.md - 长期记忆

*(暂无内容。重要的事件、决策、偏好、教训会记录在这里——阶段 7 蒸馏流水线的产出地。)*

---
"""
