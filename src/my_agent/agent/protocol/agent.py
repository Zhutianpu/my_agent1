"""Agent：持有 bot + 循环的执行体（对齐 CowAgent protocol/agent.py 的极简版）。

职责分界：
  Agent  —— 一场对话的"主持人"：找会话、记消息、跑循环、包成 Reply
  loop   —— 循环骨架本身（可被测试单独调用）
  bot    —— 纯生成器，不认识这里发生的一切
"""

import threading

from ...bridge.context import Context
from ...bridge.reply import Reply, ReplyType
from ...common import const
from ...common.log import logger
from ...config import conf
from ...models.session_manager import SESSIONS, estimate_text_tokens
from .. import mailbox
from .loop import run_loop
from .overflow import ContextOverflowError, overflow_budget, proactive_budget

# P2 在跑栈：当前线程正在运行的 (agent_id, session_id)，嵌套 run 时逐层压入。
# 用途一：agent_delegate 拒绝派单给"正在干活的 agent"（否则两个 run 共用
# 同一个 session 对象，历史当场绞麻花——CowAgent delegation_trace 的极简版）；
# 用途二：工具里能查到"我是谁"（栈顶 = 调用者），留言/委托自动署名。
_run_local = threading.local()


def running_stack() -> list:
    return list(getattr(_run_local, "stack", []))


class Agent:
    def __init__(self, bot, system_prompt: str = "", max_turns: int = None, memory=None,
                 tools=None, persist_session: bool = True):
        self.bot = bot
        # 编译好的 system prompt（阶段 5：由 initializer 装配时注入；
        # 直接 new Agent(bot) 的测试/旧代码没有它，session 退回配置的 character_desc）
        self.system_prompt = system_prompt
        # 默认 16（2026-10-28 从 8 上调）：8 是阶段 4 的保守刹车，真机里
        # 一次派单验收就烧掉 6 轮，太紧；CowAgent 默认 100。刹车防的是
        # 死循环烧 token，16 对单用户场景成本可忽略、余量够用。
        self.max_turns = max_turns or int(conf().get("agent_max_turns", 16))
        self.memory = memory  # 阶段 7：蒸馏线（None = 无记忆，测试/旧代码路径）
        # 阶段 11 子代理两件套：
        self.tools = tools  # 裁剪后的工具注册表（None = 全局 TOOLS）
        self.persist_session = persist_session  # False = 用完即弃，不落盘

    def run(self, query: str, context: Context = None) -> Reply:
        session_id = context.get("session_id") if context else None
        agent_id = (context.get("agent_id") if context else None) or const.DEFAULT_AGENT_ID
        on_event = (context.get("on_event") if context else None) or (lambda e: None)

        run_key = (agent_id, session_id or const.DEFAULT_SESSION_ID)
        stack = running_stack()
        stack.append(run_key)
        _run_local.stack = stack
        try:
            return self._run_inner(query, session_id, agent_id, on_event)
        finally:
            stack = running_stack()
            if run_key in stack:
                stack.remove(run_key)
            _run_local.stack = stack

    def _run_inner(self, query: str, session_id, agent_id: str, on_event) -> Reply:
        session = SESSIONS.build_session(session_id, agent_id)
        session.set_system_prompt(self.system_prompt)  # 刷新第 0 条，历史不碰

        # P2 信箱：上线先签收——留言并进本轮的用户消息，模型一次看全
        mails = mailbox.drain(agent_id)
        if mails:
            query = mailbox.format_mails(mails) + "用户的消息：" + query

        session.add_query(query)
        discarded = session.discard_exceeding()  # 第一把尺：条数
        # 护甲三期主动道：第二把尺 token（条数是代理指标，一条消息 10 token
        # 或 2000 token 都可能）。裁掉的一样去蒸馏。
        sys_tokens = estimate_text_tokens(session.system_prompt)
        tok_discarded, _ = session.discard_over_tokens(proactive_budget(sys_tokens))
        discarded += tok_discarded

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
        except ContextOverflowError as e:
            # 护甲三期被动道：报错即数据源——抠真实预算 → 照它裁（边界安全，
            # 裁掉的照样蒸馏保命）→ 只重试一次（CowAgent 记的 LinkAI 教训：
            # 蒙着砍一半会"压→还超→再压→再撞"锤打死循环）。
            logger.warning(f"[Agent] 上下文溢出，压缩重试: {e}")
            discarded, fits = session.discard_over_tokens(
                overflow_budget(str(e), sys_tokens))
            if discarded and self.memory:
                summary = self.memory.flush(discarded)
                if summary:
                    session.inject_summary(summary)
            if fits:
                on_event({"type": "notice", "data": {
                    "text": "（上下文撞墙：已压缩历史+蒸馏，重试一次）"}})
                try:
                    text = run_loop(
                        bot=self.bot, session=session,
                        on_event=on_event, max_turns=self.max_turns,
                        tools=self.tools,
                    )
                except ContextOverflowError:
                    fits = False  # 压缩后还撞 → 放弃，走清空兜底
            if not fits:
                # 压不动：清内存（reset 重建 system 头），不落盘——磁盘历史保住。
                # SIMPLIFIED：jsonl 整写意味着下次成功保存仍会覆盖磁盘历史；
                # CowAgent 的 SQLite 才谈得上真正长期保留。单用户场景
                # "请重新描述需求"已够兜底。
                session.reset()
                on_event({"type": "notice", "data": {
                    "text": "（上下文实在塞不下，已清空内存对话）"}})
                on_event({"type": "agent_end", "data": {}})
                return Reply(ReplyType.TEXT,
                             "上下文实在塞不下了：我已清空内存里的对话（本轮不落盘，磁盘历史保留）。"
                             "请重新描述你的需求。")
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
