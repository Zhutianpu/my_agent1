"""子代理模板：主 agent 能派哪几种工人（对齐 CowAgent subagent/templates.py）。

一个模板是一个角色，不是一个身份：name + description（父模型据它路由选角色）
+ prompt（子代理的 system prompt）+ 工具白名单。没有记忆、没有 channel、
没有花名册位置。

SIMPLIFIED：CowAgent 还支持从 workspace/subagents/*.md 加载用户自定义模板
（frontmatter 与 skills 同款）。我们只留两个内置角色；要加用户模板时复用
skills/loader.py 的 parse_frontmatter 即可——缝在这句话里。
"""

from dataclasses import dataclass, field

# 铁律：任何模板都拿不到这些工具（模板写 "*" 也会被扣掉）。
# 对我们而言最关键的只有一个：subagent 自己——子代理拿不到派单工具，
# 结构上就不可能套娃（CowAgent 除此之外还有深度计数，我们不需要：
# 工具集里没有派单工具，递归无从发起）。
BLOCKED_TOOLS = frozenset({"subagent"})

# explore 角色的只读工具集。注意 run_command 不在里面——它能改东西。
# memory_search 在里面：子代理可以翻共享记忆找背景（CowAgent 同款放行）。
READ_ONLY_TOOLS = (
    "read_file", "ls", "search_files", "current_time", "memory_search",
)

_ALL = "*"


@dataclass(frozen=True)
class SubagentTemplate:
    name: str
    description: str  # 给父模型看的路由文案：说"什么时候选它"，不说"它是什么"
    prompt: str       # 子代理的 system prompt
    tools: tuple = (_ALL,)  # ("*",) = 父工具集减去 BLOCKED；否则按名字白名单

    def select_tool_names(self, available: list) -> list:
        """从可用工具名里挑出这个角色能用的（BLOCKED 无条件先扣）。"""
        return [n for n in available
                if n not in BLOCKED_TOOLS
                and (_ALL in self.tools or n in self.tools)]


GENERAL_PURPOSE = SubagentTemplate(
    name="general-purpose",
    description="需要边查边做的多步任务：搜索、读文件、跑命令、写文件。"
                "知道目标但不确定要几步时用。",
    prompt=(
        "你是一个专注的子代理。派你来的 agent 给了你一个任务，你看不到它的对话，"
        "也不能问用户问题——一切依据都在任务和背景里。\n\n"
        "只完成任务本身，然后汇报：你查到了什么或改了什么、碰过的文件路径、"
        "以及没解决的部分。你的汇报是唯一能回到派单方手里的东西，中间步骤"
        "全部会被丢弃——重要内容别落下，但也别灌水，它要进对方的上下文窗口。"
    ),
)

EXPLORE = SubagentTemplate(
    name="explore",
    description="只读调查：找文件、搜代码或文档、收集事实。"
                "答案在某处需要找出来、且什么都不用改时用。",
    prompt=(
        "你是一个只读子代理。你调查并汇报，从不修改任何东西。你看不到派单方"
        "的对话，也不能问用户，但可以搜索和阅读共享记忆。\n\n"
        "查到够回答任务的信息就停，多余的每一步都是时间和成本。汇报要给出"
        "具体文件路径、行号或原文引用，让派单方能核对而不必重查。"
        "没找到就直说没找到，不要猜。"
    ),
    tools=READ_ONLY_TOOLS,
)

TEMPLATES = {t.name: t for t in (GENERAL_PURPOSE, EXPLORE)}
DEFAULT_TEMPLATE_NAME = GENERAL_PURPOSE.name
