"""全局测试设施。

两处全局状态必须每测试复位，否则跨文件泄漏：
- 阶段 7a 起会话会落盘到 workspaces/<agent_id>/sessions/。测试必须关掉持久化：
  否则上一次 pytest 跑出的 jsonl 会在下次 build_session 时复活旧消息，
  污染断言（真踩过的坑的形状）。需要持久化的测试（test_stage7）自己打开。
- 阶段 6 权限闸的 confirm_handler：某测试设了"全拒"handler 不复位，
  后续文件的 write 类工具调用会被莫名拒掉（test_stage9 真踩到）。
"""

import pytest

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
