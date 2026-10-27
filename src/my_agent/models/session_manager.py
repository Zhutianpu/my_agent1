"""会话层：历史的家。

Session = 一段对话的本子（messages 列表 + system_prompt）。
SessionManager = 按 session_id 存本子的柜子（get-or-create）。

SESSIONS 是全局唯一的柜子——它比任何 bot 都长寿，所以历史住这里。
换模型时 bot 被丢弃重建，柜子不动，历史无缝衔接。
P2 的缝：build_session 已带 agent_id，多 agent 时历史按 (agent_id, session_id) 隔离。
"""

from ..common import const
from ..common.log import logger
from ..config import conf


class Session:
    def __init__(self, session_id, agent_id=const.DEFAULT_AGENT_ID, system_prompt=None):
        self.session_id = session_id
        self.agent_id = agent_id
        self.system_prompt = (
            system_prompt if system_prompt is not None else conf().get("character_desc", "")
        )
        self.messages = []
        self.reset()

    def reset(self):
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def set_system_prompt(self, prompt: str):
        """刷新编译好的 system prompt（阶段 5：prompt 是编译产物，每次装配可更新）。
        只动第 0 条，历史消息不碰。"""
        if not prompt or prompt == self.system_prompt:
            return
        self.system_prompt = prompt
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = prompt
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

    def add_query(self, query: str):
        self.messages.append({"role": "user", "content": query})

    def add_reply(self, reply: str):
        self.messages.append({"role": "assistant", "content": reply})

    def discard_exceeding(self):
        """超长裁剪。SIMPLIFIED: 按消息条数裁（CowAgent 按 token 数），
        永远保住第 0 条 system prompt。
        关键教训（CowAgent 注释）：工具"订单+回执"成对，裁剪只能落在
        user 消息的边界上，否则孤儿 tool 消息会让 API 直接报错。"""
        max_msgs = conf().get("conversation_max_messages", 40)
        if len(self.messages) <= max_msgs:
            return
        # 找能容纳进预算的最早 user 边界
        start = 1
        for i, m in enumerate(self.messages):
            if i > 0 and m.get("role") == "user" and len(self.messages) - i <= max_msgs - 1:
                start = i
                break
        self.messages = [self.messages[0]] + self.messages[start:]
        # 兜底清理：开头绝不能是 tool 回执或挂着订单的 assistant
        while len(self.messages) > 1 and (
            self.messages[1].get("role") == "tool" or self.messages[1].get("tool_calls")
        ):
            self.messages.pop(1)


class SessionManager:
    def __init__(self):
        self.sessions = {}

    def build_session(self, session_id=None, agent_id=const.DEFAULT_AGENT_ID,
                      system_prompt=None) -> Session:
        key = (agent_id, session_id or const.DEFAULT_SESSION_ID)
        if key not in self.sessions:
            self.sessions[key] = Session(key[1], agent_id, system_prompt)
            logger.debug(f"[Session] 新本子: {key}")
        return self.sessions[key]

    def clear_session(self, session_id=None, agent_id=const.DEFAULT_AGENT_ID):
        self.sessions.pop((agent_id, session_id or const.DEFAULT_SESSION_ID), None)


SESSIONS = SessionManager()
