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
    # 阶段 7：None = 无记忆系统（裸 Agent/测试，整段不出现——否则模型会幻觉调用
    # 不存在的 memory_search）；"" = 有记忆系统但今天还没日记（教育在、摘要不在）
    memory_digest: Optional[str] = None,
    skill_manager=None,               # 阶段 8：技能清单（有 build_skills_prompt() 就行）
) -> str:
    """分段编译 system prompt。每段由原料是否存在决定（存在即编译）。"""
    sections = []

    # 兜底身份：workspace 文件全空时（比如被清空了），退回配置里的性格描述
    if not context_files and identity_fallback:
        sections.append(identity_fallback.strip())

    # 1. 工具段（最重要，放最前——对齐 CowAgent 的段序）
    if tools:
        sections.append(_tools_section(tools))

    # 2. 工作空间说明段（agent 得知道"家"在哪、cwd 在哪、文件各是什么）
    if runtime_info and runtime_info.get("workspace_dir"):
        sections.append(_workspace_section(
            runtime_info["workspace_dir"], runtime_info.get("cwd", "")))

    # 3. 记忆段（阶段 7）：能力门控不对内容门控——召回路径的教育必须在，
    # 否则日记为空时模型学不到"可以搜记忆"，问过去的事搜不搜成抛硬币
    # （50 轮召回评估实测 A 层 0→9→0 摆动抓到的；对齐 CowAgent 的
    #  if memory_manager: 门控 + "Memory Recall (mandatory)" 教育）。
    if memory_digest is not None:
        sections.append(_memory_section(memory_digest))

    # 3.5. 技能段（阶段 8）：描述清单 + 使用纪律（正文不进 prompt，模型按需读）
    if skill_manager:
        skills_prompt = skill_manager.build_skills_prompt()
        if skills_prompt:
            sections.append(_skills_section(skills_prompt))

    # 4. 上下文文件段（AGENT.md 在这里变成"我是谁"）
    if context_files:
        sections.append(_context_files_section(context_files))

    # 5. 运行时信息段（元信息放最后——对齐 CowAgent）
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


def _workspace_section(workspace_dir: str, cwd: str = "") -> str:
    lines = [
        "## 🏠 工作空间",
        "",
        f"你的工作目录：`{workspace_dir}`——这是你的家，里面的文件定义了你是谁。",
        "",
        "- `AGENT.md`：你的身份与行为准则（可随成长用 edit_file 更新）",
        "- `USER.md`：用户的基本信息（了解到的静态信息写进去）",
        "- `MEMORY.md`：长期记忆（重要的事写下来，不要只在心里记）",
        "- `memory/`：每日记录目录",
        "- `skills/`：技能目录（每个子目录一份 SKILL.md 说明书）",
    ]
    if cwd:
        lines += [
            "",
            f"工具的当前工作目录（cwd）是：`{cwd}`。用户说的项目文件大多在那里，",
            "不在你的家里——家里找不到时，用相对路径（如 `PLAN.md`）或绝对路径直接去 cwd 找。",
        ]
    return "\n".join(lines)


def _memory_section(digest: str) -> str:
    # 教育部分无条件在（这是召回路径说明书）；digest 数据有料才附。
    # 对齐 CowAgent "Memory Recall (mandatory)"，极简成两句。
    lines = [
        "## 🧠 记忆系统",
        "",
        "当用户问起过去的事（偏好、决定、待办、之前说过的信息），先用 memory_search "
        "检索再回答——早前的对话可能已蒸馏进日记，不在当前上下文里。",
        "搜不到就如实说没有记录，不要凭印象编造。",
    ]
    if digest:
        lines += [
            "",
            "以下是最近日记的摘要（更早的记忆用 memory_search 检索；",
            "重要但已过时的内容会在 #dream 后沉淀进 MEMORY.md）：",
            "",
            digest,
        ]
    return "\n".join(lines)


def _skills_section(skills_prompt: str) -> str:
    """技能段：描述清单 + 使用纪律（对齐 CowAgent _build_skills_section 的中文版）。

    纪律必须写死在 prompt 里：技能不是工具、不能调，唯一用法是 read_file
    读 SKILL.md 后照做——模型不看正文就会瞎猜技能内容。"""
    return "\n".join([
        "## 🧩 技能系统（mandatory）",
        "",
        "在回复之前：扫描下方每个技能的描述。",
        "",
        "- 如果有技能的描述与用户需求匹配：用 `read_file` 读取其路径下的 SKILL.md，",
        "  然后严格遵循文件中的指令。有匹配的技能时优先使用技能",
        "- 多个技能都适用时选最匹配的一个，读完再做",
        "- 没有技能明确适用时：不要读任何 SKILL.md，直接用通用工具",
        "",
        "**重要**：技能不是工具，不能直接调用。使用技能的唯一方式是用 `read_file`",
        "读取 SKILL.md 然后按内容操作。一次只读一个技能，选中再读。",
        "",
        "以下是可用技能：",
        "",
        skills_prompt,
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
