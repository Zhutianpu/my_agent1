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
    def __init__(self, bot, system_prompt: str = "", max_turns: int = None, memory=None,
                 tools=None, persist_session: bool = True):
        self.bot = bot
        # 编译好的 system prompt（阶段 5：由 initializer 装配时注入；
        # 直接 new Agent(bot) 的测试/旧代码没有它，session 退回配置的 character_desc）
        self.system_prompt = system_prompt
        self.max_turns = max_turns or int(conf().get("agent_max_turns", 8))
        self.memory = memory  # 阶段 7：蒸馏线（None = 无记忆，测试/旧代码路径）
        # 阶段 11 子代理两件套：
        self.tools = tools  # 裁剪后的工具注册表（None = 全局 TOOLS）
        self.persist_session = persist_session  # False = 用完即弃，不落盘

    def run(self, query: str, context: Context = None) -> Reply:
        session_id = context.get("session_id") if context else None
        agent_id = (context.get("agent_id") if context else None) or const.DEFAULT_AGENT_ID
        on_event = (context.get("on_event") if context else None) or (lambda e: None)

        session = SESSIONS.build_session(session_id, agent_id)
        session.set_system_prompt(self.system_prompt)  # 刷新第 0 条，历史不碰
        session.add_query(query)
        discarded = session.discard_exceeding()  # 循环外只裁一次；裁掉的去蒸馏

        # 7b：裁剪即蒸馏——必须在循环前做（对齐 CowAgent 的时机）。
        # 真机教训：曾在回复后才蒸馏，结果"刚写完周报、上下文被裁、用户回复时
        # 模型当场失忆"。摘要注回活上下文（context_summary_callback 同款），
        # 模型这轮就能看见"早前聊了什么的浓缩版"。
        if discarded and self.memory:
            summary = self.memory.flush(discarded)
            if summary:
                session.inject_summary(summary)

        on_event({"type": "agent_start", "data": {}})
        try:
            text = run_loop(
                bot=self.bot, session=session,
                on_event=on_event, max_turns=self.max_turns,
                tools=self.tools,
            )
        except KeyboardInterrupt:
            # 护甲二期：中断发生在循环外（罕见，比如蒸馏时按了 Ctrl+C）。
            # 循环内的中断 loop 自己接住并正常返回了。这里兜住 = 应用不死。
            logger.warning("[Agent] 运行被中断（循环外）")
            on_event({"type": "notice", "data": {"text": "（这轮执行被中断）"}})
            session.add_reply("（这轮执行被中断）")  # 保持一问一答
            self._save(session)
            on_event({"type": "agent_end", "data": {}})
            return Reply(ReplyType.TEXT, "（这轮执行被中断）")
        except Exception as e:
            logger.exception("[Agent] 循环异常")
            on_event({"type": "error", "data": {"error": str(e)}})
            self._save(session)  # 炸了也要保住历史
            return Reply(ReplyType.ERROR, f"出错了: {e}")
        on_event({"type": "agent_end", "data": {}})
        self._save(session)  # 7a：落盘
        return Reply(ReplyType.TEXT, text)

    def _save(self, session):
        """落盘（子代理的弃置 session 跳过：它的历史只属于这次派单）。"""
        if self.persist_session:
            SESSIONS.save_session(session)
