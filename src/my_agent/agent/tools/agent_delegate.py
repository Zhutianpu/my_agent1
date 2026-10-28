"""agent_delegate 派单工具：把任务委托给花名册里的另一个 agent（P2）。

对齐 CowAgent tools/agent_delegate/agent_delegate.py（719 行）的核心契约：
- delegated_prompt：任务包上来源说明 + "把简洁结果返回给委托方，不要直接
  对用户说话"——对方的回复由委托方用自己的话转述给用户
- 循环防护：CowAgent 用 delegation_trace 元组 + max_depth=3 双重挡；
  我们结构级挡（阶段 11 同一招）：被派单者的工具集里没有 agent_delegate，
  它想再派都没家伙。再加一层"在跑栈"检查：不能派给正在干活的 agent
  （否则两个 run 嵌套进同一个 session，历史当场绞麻花）

与 subagent 的分工（选型写进 description，模型自己挑）：
- subagent：临时雇工。上下文隔离、用完即弃、任务必须自包含
- agent_delegate：同事协作。对方有自己的人设/记忆/工作目录/持久会话——
  干过的活它记得住，#use 切过去能接着聊

SIMPLIFIED：无 max_depth 配置（结构级不需要）、无 trace 参数、无并发派单、
无事件转播（对方埋头干活，只把结论带回来；要看实况用 #use 切过去）。
"""

from ...common import const
from ...common.log import logger
from ..roster import load_roster
from .base_tool import BaseTool, ToolResult

_BASE_DESC = (
    "把一个任务委托给花名册里的另一个 agent，等它干完并把它的结论带回来。\n\n"
    "对方是正式同事：有自己的人设、记忆和独立工作目录，这次委托会留在它的"
    "会话里（它记得住）。适合需要特定角色专长、或希望对方持续跟进的事。\n"
    "任务要写完整（对方看不到这场对话），但不用像 subagent 那样强调自包含——"
    "它有自己的记忆可以查。\n\n"
    "对方的回复不会直接给用户看——读完后用你自己的话转述重点。\n\n"
    "花名册（可委托对象）：\n"
)


class AgentDelegateTool(BaseTool):
    name = "agent_delegate"
    risk = "read"  # 派单动作本身不改东西；对方用的每个工具照常过权限闸
    params = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string",
                         "description": "花名册里的 agent id（见工具描述清单）。"},
            "task": {"type": "string",
                     "description": "委托给对方的完整任务说明：要做什么、关键背景、期望带回什么结论。"},
        },
        "required": ["agent_id", "task"],
    }

    def schema(self) -> dict:
        """实例方法遮蔽类方法（McpTool 同款）：花名册现读现编，改配置即生效。"""
        listing = "\n".join(
            f"- {p.id}（{p.name}）: {p.description or '（无描述）'}"
            for p in load_roster().values()
        )
        return {"type": "function", "function": {
            "name": self.name,
            "description": _BASE_DESC + listing,
            "parameters": self.params,
        }}

    def execute(self, agent_id="", task="") -> ToolResult:
        task = str(task or "").strip()
        if not task:
            return ToolResult.fail("error: task 不能为空——对方看不到这场对话，任务得写完整")
        roster = load_roster()
        profile = roster.get(str(agent_id).strip())
        if profile is None:
            return ToolResult.fail(
                f"error: 花名册里没有 '{agent_id}'（在册的: {', '.join(sorted(roster))}）")

        # 在跑栈检查：目标正在干活（往往就是我自己）时派单 = 会话嵌套
        from ..protocol.agent import running_stack  # 局部 import 破环
        stack = running_stack()
        if (profile.id, const.DEFAULT_SESSION_ID) in stack:
            return ToolResult.fail(
                f"error: {profile.id} 正在干活（很可能就是你自己）——不能派单给在跑的 agent")
        source = stack[-1][0] if stack else "unknown"

        from ...bridge.bridge import Bridge
        from ...bridge.context import Context, ContextType
        from ..protocol.agent import Agent
        from .tool_manager import TOOLS

        base = Bridge().get_agent(profile.id)  # 装配间的缓存：人设/记忆/bot 都现成
        # 结构级防循环：对方的工具集里没有 agent_delegate（阶段 11 白名单同一招）
        peer_tools = TOOLS.subset(n for n in TOOLS._tools if n != self.name)
        peer = Agent(bot=base.bot, system_prompt=base.system_prompt,
                     max_turns=base.max_turns, memory=base.memory, tools=peer_tools)
        # 委托进对方的主会话（不是隔离的临时会话）——它记得住这次协作，
        # #use 切过去能接着聊。这是和 subagent 的核心区别。
        delegated = (f"[来自 agent「{source}」的委托]\n\n任务：{task}\n\n"
                     f"请把简洁的结果返回给委托方——你的回复不会直接给用户看，由委托方转述。")
        logger.info(f"[Delegate] {source} → {profile.id}: {task[:60]}")
        reply = peer.run(delegated, Context(
            ContextType.TEXT, delegated,
            kwargs={"session_id": const.DEFAULT_SESSION_ID,
                    "agent_id": profile.id,
                    "on_event": lambda e: None},  # 埋头干活不转播
        ))
        if reply.type.name == "ERROR":  # ERROR 是 Reply 不是异常（阶段 11 的教训）
            return ToolResult.fail(f"error: {profile.id} 干活时出错: {reply.content}")
        return ToolResult.success(f"[{profile.name}({profile.id}) 的回复]\n{reply.content}")
