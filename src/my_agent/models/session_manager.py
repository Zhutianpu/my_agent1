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


def estimate_text_tokens(text: str) -> int:
    """token 粗算（对齐 CowAgent _estimate_text_tokens）：CJK ×1.5，ASCII ÷4。

    估算不怕糙——主动道有 20% 输出预留，被动道有 10% 余量 +
    报错里的真实数字兜底。SIMPLIFIED：CowAgent 还给 tool_use/tool_result
    块加 +50/+30 结构开销、图片固定 1200；我们的 content 是纯字符串，
    结构开销只在 Session.estimate_tokens 里对 tool_calls 加一次。
    """
    if not text:
        return 0
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return int(non_ascii * 1.5 + (len(text) - non_ascii) * 0.25) + 1


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

    def get_summary(self) -> str:
        """读当前摘要注回的内容（不含标记行），没有返回 ""。

        滚动蒸馏用：旧摘要要并入下一批蒸馏输入（agent.py 蒸馏段），
        否则摘要是"单代容器"——每批一换，早期事实活不过两代。"""
        if len(self.messages) > 1 and self.messages[1].get("role") == "system" \
                and str(self.messages[1].get("content", "")).startswith(self.SUMMARY_MARK):
            return self.messages[1]["content"][len(self.SUMMARY_MARK):].strip()
        return ""

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

    # ---- 护甲三期：token 预算裁剪（条数之外的第二把尺子） ----

    _OLD_TOOL_RESULT_CHARS = 500  # 老轮次工具结果截断到这个数（写入上限 6000 对历史太松）
    _TRUNC_MARK = "…（历史工具结果已截断）"

    def estimate_tokens(self) -> int:
        """整本历史的粗算。system 头群不计——它在预算公式里单独减
        （对齐 CowAgent：budget = window − reserve − system_tokens，
        再拿来和轮次 token 比）。"""
        total = 0
        for m in self.messages:
            if m.get("role") == "system":
                continue
            c = m.get("content")
            if isinstance(c, str):
                total += estimate_text_tokens(c)
            tcs = m.get("tool_calls")
            if tcs:  # 工具订单：JSON 参数 + 结构开销
                total += estimate_text_tokens(json.dumps(tcs, ensure_ascii=False)) + 50
        return total

    def _truncate_old_tool_results(self):
        """老轮次的 tool 结果截断（最后一轮不动——模型可能还要引用）。
        对齐 CowAgent _trim_messages Step 0（30K→10K）：整轮丢之前，
        先把能省的都省了。"""
        last_user = 0
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                last_user = i
                break
        for m in self.messages[:last_user]:
            if m.get("role") == "tool":
                c = m.get("content") or ""
                if len(c) > self._OLD_TOOL_RESULT_CHARS:
                    m["content"] = c[:self._OLD_TOOL_RESULT_CHARS] + self._TRUNC_MARK

    def _discard_oldest_turn(self) -> list:
        """按 user 边界丢最老一轮（system 头群和最后一轮永远不动——
        用户刚说的话不能丢，CowAgent 同款）。返回被丢的消息，无可丢返回 []。"""
        head = 0
        while head < len(self.messages) and self.messages[head].get("role") == "system":
            head += 1
        users = [i for i in range(head, len(self.messages))
                 if self.messages[i].get("role") == "user"]
        if len(users) <= 1:
            return []
        cut = users[1]  # 第二轮开始的地方 = 第一轮的结束
        batch = self.messages[head:cut]
        self.messages = self.messages[:head] + self.messages[cut:]
        return batch

    def discard_over_tokens(self, budget: int):
        """token 预算裁剪（对齐 _trim_messages Step 0/3 + _smart_compact_to_budget
        的循环压缩，合成一个入口）。裁剪即蒸馏的触发点不变：返回 (被丢的消息, 是否达标)。

        fits=False 时消息可能已截断/已丢但仍超（比如只剩一轮巨物）——
        被丢的部分照样返回给调用方蒸馏（CowAgent 压不动前也先 flush 保命）。
        """
        if self.estimate_tokens() <= budget:
            return [], True
        self._truncate_old_tool_results()
        discarded = []
        guard = 0
        while self.estimate_tokens() > budget and guard < 32:  # guard 上限对齐 CowAgent
            guard += 1
            batch = self._discard_oldest_turn()
            if not batch:
                break  # 只剩最后一轮——不能再丢
            discarded.extend(batch)
        return discarded, self.estimate_tokens() <= budget


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
