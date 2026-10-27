"""Agent：持有 bot + 循环的执行体（对齐 CowAgent protocol/agent.py 的极简版）。

职责分界：
  Agent  —— 一场对话的"主持人"：找会话、记消息、跑循环、包成 Reply
  loop   —— 循环骨架本身（可被测试单独调用）
  bot    —— 纯生成器，不认识这里发生的一切
"""

from ...bridge.context import Context
from ...bridge.reply import Reply, ReplyType
from ...common import const
from ...common.log import logger
from ...config import conf
from ...models.session_manager import SESSIONS
from .loop import run_loop


class Agent:
    def __init__(self, bot, max_turns: int = None):
        self.bot = bot
        self.max_turns = max_turns or conf().get("agent_max_turns", 8)

    def run(self, query: str, context: Context = None) -> Reply:
        session_id = context.get("session_id") if context else None
        agent_id = (context.get("agent_id") if context else None) or const.DEFAULT_AGENT_ID
        on_event = (context.get("on_event") if context else None) or (lambda e: None)

        session = SESSIONS.build_session(session_id, agent_id)
        session.add_query(query)
        session.discard_exceeding()  # 循环外只裁一次

        on_event({"type": "agent_start", "data": {}})
        try:
            text = run_loop(
                bot=self.bot, session=session,
                on_event=on_event, max_turns=self.max_turns,
            )
        except Exception as e:
            logger.exception("[Agent] 循环异常")
            on_event({"type": "error", "data": {"error": str(e)}})
            return Reply(ReplyType.ERROR, f"出错了: {e}")
        on_event({"type": "agent_end", "data": {}})
        return Reply(ReplyType.TEXT, text)
