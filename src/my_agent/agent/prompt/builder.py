"""Prompt 编译器（对齐 CowAgent agent/prompt/builder.py 的简化版）。

核心契约：build_system_prompt 是纯函数——原料进，字符串出。
核心设计：**分段 + 存在即编译**。每段都由"原料是否存在"决定编不编，
所以阶段 7（记忆）、阶段 8（技能）接入时，本文件一行不改，
只是调用方多传一个原料（memory_manager= / skill_manager= 的坑位已留）。

SIMPLIFIED: CowAgent 有 8 段（含技能/记忆/知识库/权限/团队/双语切换）。
本阶段只编四段：工具 → 工作空间说明 → 上下文文件 → 运行时信息。
记忆段、技能段的开关位置已在注释里标出。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ContextFile:
    """workspace 里读出来的一份文件（对齐 CowAgent builder.ContextFile）。"""
    path: str      # 相对 workspace 的文件名，如 "AGENT.md"
    content: str   # 文件全文


def build_system_prompt(
    *,
    tools: Optional[List[dict]] = None,
    context_files: Optional[List[ContextFile]] = None,
    runtime_info: Optional[Dict[str, Any]] = None,
    identity_fallback: str = "",
    # 阶段 7 坑位：memory_digest=None
    # 阶段 8 坑位：skill_manager=None
) -> str:
    """分段编译 system prompt。每段由原料是否存在决定（存在即编译）。"""
    sections = []

    # 兜底身份：workspace 文件全空时（比如被清空了），退回配置里的性格描述
    if not context_files and identity_fallback:
        sections.append(identity_fallback.strip())

    # 1. 工具段（最重要，放最前——对齐 CowAgent 的段序）
    if tools:
        sections.append(_tools_section(tools))

    # 2. 工作空间说明段（agent 得知道"家"在哪、文件各是什么）
    if runtime_info and runtime_info.get("workspace_dir"):
        sections.append(_workspace_section(runtime_info["workspace_dir"]))

    # 阶段 7：记忆摘要段插在这里（memory_digest）
    # 阶段 8：技能清单段插在这里（skill_manager）

    # 3. 上下文文件段（AGENT.md 在这里变成"我是谁"）
    if context_files:
        sections.append(_context_files_section(context_files))

    # 4. 运行时信息段（元信息放最后——对齐 CowAgent）
    if runtime_info:
        sections.append(_runtime_section(runtime_info))

    return "\n\n".join(s for s in sections if s)


def _tools_section(tools: List[dict]) -> str:
    """工具清单 + 使用原则。tools 是 OpenAI function 格式的 schema 列表。"""
    lines = ["## 🔧 工具系统", "", "你可以通过 function calling 调用以下工具："]
    for schema in tools:
        fn = schema.get("function", schema)
        lines.append(f"- **{fn.get('name')}**：{fn.get('description', '')}")
    lines += [
        "",
        "使用原则：",
        "- 先查再问：能用工具查证的，不要凭记忆猜",
        "- 工具失败会返回错误文本，读懂原因后换参数或换方案重试",
        "- 复杂任务分多轮调用，一轮可以只干一件事",
    ]
    return "\n".join(lines)


def _workspace_section(workspace_dir: str) -> str:
    return "\n".join([
        "## 🏠 工作空间",
        "",
        f"你的工作目录：`{workspace_dir}`——这是你的家，里面的文件定义了你是谁。",
        "",
        "- `AGENT.md`：你的身份与行为准则（可随成长用 edit_file 更新）",
        "- `USER.md`：用户的基本信息（了解到的静态信息写进去）",
        "- `MEMORY.md`：长期记忆（重要的事写下来，不要只在心里记）",
        "- `memory/`：每日记录目录",
    ])


def _context_files_section(context_files: List[ContextFile]) -> str:
    parts = ["## 📄 工作空间文件", "", "以下是你的工作空间文件当前的内容："]
    for cf in context_files:
        parts.append(f"\n### {cf.path}\n\n{cf.content}")
    return "\n".join(parts)


def _runtime_section(runtime_info: Dict[str, Any]) -> str:
    lines = ["## ⏱️ 运行时信息"]
    if runtime_info.get("now"):
        lines.append(f"- 当前时间：{runtime_info['now']}")
    if runtime_info.get("model"):
        lines.append(f"- 当前模型：{runtime_info['model']}")
    if runtime_info.get("agent_id"):
        lines.append(f"- agent_id：{runtime_info['agent_id']}")
    return "\n".join(lines)
