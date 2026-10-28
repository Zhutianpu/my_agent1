"""全局测试设施。

三处全局状态必须每测试复位/隔离，否则跨文件泄漏：
- 阶段 7a 起会话会落盘到 workspaces/<agent_id>/sessions/。测试必须关掉持久化：
  否则上一次 pytest 跑出的 jsonl 会在下次 build_session 时复活旧消息，
  污染断言（真踩过的坑的形状）。需要持久化的测试（test_stage7）自己打开。
- 阶段 6 权限闸的 confirm_handler：某测试设了"全拒"handler 不复位，
  后续文件的 write 类工具调用会被莫名拒掉（test_stage9 真踩到）。
- P2 信箱：Agent.run 每次都会 drain(agent_id) 并删除 mailbox.jsonl。
  不隔离的话，测试跑一遍就把用户真机信箱里的留言吃掉
  （2026-10-28 真发生：验收留言被 110 全绿的那次 pytest 吞了）。
"""

import pytest

from my_agent.agent import mailbox
from my_agent.agent.permission import GATE
from my_agent.models.session_manager import SESSIONS


@pytest.fixture(autouse=True)
def _isolated_sessions():
    SESSIONS.persist = False
    SESSIONS.sessions.clear()
    GATE.reset()
    yield
    SESSIONS.sessions.clear()
    SESSIONS.persist = True
    GATE.reset()


@pytest.fixture(autouse=True)
def _isolated_mailbox(tmp_path, monkeypatch):
    """信箱重定向到临时目录：测试随便 drain，碰不到真机 workspaces/。"""
    monkeypatch.setattr(mailbox, "ROOT", tmp_path)

