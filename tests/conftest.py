"""全局测试设施。

阶段 7a 起会话会落盘到 workspaces/<agent_id>/sessions/。测试必须关掉持久化：
否则上一次 pytest 跑出的 jsonl 会在下次 build_session 时复活旧消息，
污染断言（真踩过的坑的形状）。需要持久化的测试（test_stage7）自己打开。
"""

import pytest

from my_agent.models.session_manager import SESSIONS


@pytest.fixture(autouse=True)
def _isolated_sessions():
    SESSIONS.persist = False
    SESSIONS.sessions.clear()
    yield
    SESSIONS.sessions.clear()
    SESSIONS.persist = True
