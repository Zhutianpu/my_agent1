"""会话层：历史的家（阶段 7 版：jsonl 持久化）。

Session = 一段对话的本子（messages 列表 + system_prompt）。
SessionManager = 按 (agent_id, session_id) 存本子的柜子（get-or-create）。

SESSIONS 是全局唯一的柜子——它比任何 bot 都长寿，所以历史住这里。
换模型时 bot 被丢弃重建，柜子不动，历史无缝衔接。

阶段 7a：每个会话落盘成 workspaces/<agent_id>/sessions/<session_id>.jsonl
（整文件重写——裁剪后文件必须与内存一致，append 做不到）。
重启时 build_session 自动恢复。SIMPLIFIED: CowAgent 用 SQLite
（conversation_store.py 3161 行），jsonl 对单用户终端够用且肉眼可查。
"""

import json
from pathlib import Path

from ..common import const
from ..common.log import logger
from ..config import ROOT, conf


def _session_file(agent_id, session_id) -> Path:
    sid = session_id or const.DEFAULT_SESSION_ID
    return ROOT / "workspaces" / agent_id / "sessions" / f"{sid}.jsonl"


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
        user 消息的边界上，否则孤儿 tool 消息会让 API 直接报错。

        阶段 7：返回被裁掉的消息列表——裁剪即蒸馏的触发点
        （CowAgent summarizer 的同款触发设计）。"""
        max_msgs = int(conf().get("conversation_max_messages", 40))  # env 覆盖是字符串，必须转
        if len(self.messages) <= max_msgs:
            return []
        # 找能容纳进预算的最早 user 边界
        start = 1
        for i, m in enumerate(self.messages):
            if i > 0 and m.get("role") == "user" and len(self.messages) - i <= max_msgs - 1:
                start = i
                break
        discarded = self.messages[1:start]
        self.messages = [self.messages[0]] + self.messages[start:]
        # 兜底清理：开头绝不能是 tool 回执或挂着订单的 assistant
        while len(self.messages) > 1 and (
            self.messages[1].get("role") == "tool" or self.messages[1].get("tool_calls")
        ):
            discarded.append(self.messages.pop(1))
        return discarded


class SessionManager:
    def __init__(self):
        self.sessions = {}
        self.persist = True  # 7a 持久化开关；测试经 conftest 关掉（防跨测试运行污染）

    def build_session(self, session_id=None, agent_id=const.DEFAULT_AGENT_ID,
                      system_prompt=None) -> Session:
        key = (agent_id, session_id or const.DEFAULT_SESSION_ID)
        if key not in self.sessions:
            session = Session(key[1], agent_id, system_prompt)
            if self.persist:
                self._load(session)  # 7a：磁盘上有本子就恢复
            self.sessions[key] = session
            logger.debug(f"[Session] 新本子: {key}（{len(session.messages)} 条消息）")
        return self.sessions[key]

    def _load(self, session: Session):
        f = _session_file(session.agent_id, session.session_id)
        if not f.exists():
            return
        try:
            messages = [json.loads(line) for line in
                        f.read_text(encoding="utf-8").splitlines() if line.strip()]
            if messages:
                session.messages = messages
                if messages[0].get("role") == "system":
                    session.system_prompt = messages[0].get("content", "")
                logger.info(f"[Session] 恢复历史: {f.name}（{len(messages)} 条）")
        except Exception:
            logger.exception(f"[Session] 恢复失败: {f}")

    def save_session(self, session: Session):
        """整文件重写（裁剪后内存即真相）。失败只记日志，不炸对话。"""
        if not self.persist:
            return
        try:
            f = _session_file(session.agent_id, session.session_id)
            f.parent.mkdir(parents=True, exist_ok=True)
            with f.open("w", encoding="utf-8") as fh:
                for m in session.messages:
                    fh.write(json.dumps(m, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("[Session] 落盘失败")

    def clear_session(self, session_id=None, agent_id=const.DEFAULT_AGENT_ID):
        key = (agent_id, session_id or const.DEFAULT_SESSION_ID)
        self.sessions.pop(key, None)
        _session_file(*key).unlink(missing_ok=True)  # #reset 连磁盘一起清


SESSIONS = SessionManager()
