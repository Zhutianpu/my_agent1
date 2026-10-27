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

    # 蒸馏摘要注回消息的固定标记（inject_summary / discard_exceeding 都认它）
    SUMMARY_MARK = "【早前对话的蒸馏摘要】"

    def inject_summary(self, summary: str):
        """把蒸馏摘要作为 system 消息注回到头部（紧跟编译 prompt 之后）。
        已存在就替换（摘要随蒸馏滚动更新，不堆积）。
        对齐 CowAgent context_summary_callback：裁掉的上下文以浓缩形态留在场上。"""
        note = {"role": "system", "content": f"{self.SUMMARY_MARK}\n{summary}"}
        if len(self.messages) > 1 and self.messages[1].get("role") == "system" \
                and str(self.messages[1].get("content", "")).startswith(self.SUMMARY_MARK):
            self.messages[1] = note
        else:
            self.messages.insert(1, note)

    def discard_exceeding(self):
        """超长裁剪。SIMPLIFIED: 按消息条数裁（CowAgent 按 token 数）。

        保护清单（裁剪的高压线）：
        - 开头的 system 消息群（编译 prompt + 蒸馏摘要注回）永远保留
        - 裁剪只能落在 user 边界上（工具"订单+回执"成对，孤儿 tool 消息会让 API 报错）

        返回被裁掉的消息列表——裁剪即蒸馏的触发点。"""
        max_msgs = int(conf().get("conversation_max_messages", 40))  # env 覆盖是字符串，必须转
        if len(self.messages) <= max_msgs:
            return []
        # 头部 system 群（编译 prompt + 可能的摘要注回）不参与裁剪
        head = 0
        while head < len(self.messages) and self.messages[head].get("role") == "system":
            head += 1
        # 找能容纳进预算的最早 user 边界
        start = None
        for i in range(head, len(self.messages)):
            if self.messages[i].get("role") == "user" and head + (len(self.messages) - i) <= max_msgs:
                start = i
                break
        if start is None:
            return []  # 一个 user 轮本身就超预算（工具消息太多）：保全部，下轮再说
        discarded = self.messages[head:start]
        self.messages = self.messages[:head] + self.messages[start:]
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
