"""agent_message 留言工具：给另一个 agent 的信箱投递异步消息（P2）。

对齐 CowAgent transport 的 MODE_SPEAK：不需要对方立刻干活的知会/备忘。
和 agent_delegate 的分工写进 description：
- 要结果 → agent_delegate（同步等回复）
- 知会一声 → agent_message（写进信箱，对方下次被唤醒才签收）
"""

from ...common import const
from .. import mailbox
from ..roster import load_roster
from .base_tool import BaseTool, ToolResult


class AgentMessageTool(BaseTool):
    name = "agent_message"
    risk = "read"  # 只是往对方信箱里追加一行
    description = (
        "给花名册里的另一个 agent 留言：写进它的信箱，它下次被唤醒时才看到"
        "（异步，你不等回复）。适合知会、备忘、交接背景。\n"
        "如果需要对方立刻干活并带回结果，用 agent_delegate。"
    )
    params = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "花名册里的 agent id。"},
            "message": {"type": "string", "description": "留言内容。"},
            "from_agent": {"type": "string",
                           "description": "署名（你自己的 agent id，运行时信息里有）。缺省自动填。"},
        },
        "required": ["agent_id", "message"],
    }

    def execute(self, agent_id="", message="", from_agent="") -> ToolResult:
        message = str(message or "").strip()
        if not message:
            return ToolResult.fail("error: message 不能为空")
        roster = load_roster()
        target = str(agent_id).strip()
        if target not in roster:
            return ToolResult.fail(
                f"error: 花名册里没有 '{agent_id}'（在册的: {', '.join(sorted(roster))}）")

        from ..protocol.agent import running_stack  # 局部 import 破环
        stack = running_stack()
        caller = stack[-1][0] if stack else "unknown"
        if target == caller:
            return ToolResult.fail("error: 给自己留言没意义——你想到的就直接记住")

        mailbox.send(target, from_agent.strip() or caller, message)
        return ToolResult.success(
            f"已投进 {target}（{roster[target].name}）的信箱——它下次被唤醒时签收")
