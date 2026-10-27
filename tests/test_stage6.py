"""阶段 6 验收测试：permission 权限闸。

核心验证：危险操作先问用户；拒绝变错误文本回填模型（D004 延伸）；
"此类都允许"记住后不再问；headless（无 handler）放行——老测试靠这个保持绿色。
"""

import json
from types import SimpleNamespace

from my_agent.agent.permission import GATE
from my_agent.agent.protocol.agent import Agent
from my_agent.agent.tools import TOOLS
from my_agent.bridge.context import Context
from my_agent.models.openai_compatible_bot import OpenAICompatibleBot
from my_agent.models.session_manager import SESSIONS


def setup_function():
    GATE.reset()
    SESSIONS.sessions.clear()


def _write_args(tmp_path, name="x.txt"):
    return json.dumps({"path": str(tmp_path / name), "content": "数据"})


# ---------- 闸门单元 ----------

def test_read_tools_never_ask(tmp_path):
    """只读工具自动放行，即使 handler 会拒也不该被叫到。"""
    GATE.confirm_handler = lambda name, args: "n"  # 全拒 handler
    f = tmp_path / "a.txt"
    f.write_text("hi", encoding="utf-8")
    assert TOOLS.execute("read_file", json.dumps({"path": str(f)})).status == "success"
    assert TOOLS.execute("current_time", "{}").status == "success"


def test_deny_becomes_error_text(tmp_path):
    GATE.confirm_handler = lambda name, args: "n"
    r = TOOLS.execute("write_file", _write_args(tmp_path))
    assert r.status == "error" and "拒绝" in r.result
    assert not (tmp_path / "x.txt").exists()  # 真没写


def test_allow_once_asks_every_time(tmp_path):
    calls = []
    GATE.confirm_handler = lambda name, args: calls.append(name) or "y"
    TOOLS.execute("write_file", _write_args(tmp_path, "1.txt"))
    TOOLS.execute("write_file", _write_args(tmp_path, "2.txt"))
    assert calls == ["write_file", "write_file"]  # 每次都问
    assert "write_file" not in GATE.remembered


def test_allow_always_remembered(tmp_path):
    calls = []
    GATE.confirm_handler = lambda name, args: calls.append(name) or "a"
    TOOLS.execute("write_file", _write_args(tmp_path, "1.txt"))
    TOOLS.execute("write_file", _write_args(tmp_path, "2.txt"))
    assert calls == ["write_file"]  # 第二次没再问
    # 记住是按工具名的：edit_file 是另一类，仍要问
    TOOLS.execute("edit_file", json.dumps({
        "path": str(tmp_path / "1.txt"), "old_text": "数", "new_text": "数"}))
    assert calls == ["write_file", "edit_file"]


def test_headless_allows(tmp_path):
    """无 handler = headless/测试模式 = 放行（老测试靠这个保持绿）。"""
    assert GATE.confirm_handler is None
    assert TOOLS.execute("write_file", _write_args(tmp_path)).status == "success"


def test_gate_failure_fails_open(tmp_path):
    """闸自身炸了也不能炸掉对话（fail-open + 日志）。"""
    def boom(name, args):
        raise RuntimeError("handler 炸了")
    GATE.confirm_handler = boom
    assert TOOLS.execute("write_file", _write_args(tmp_path)).status == "success"


# ---------- 循环集成：模型收到拒绝后换方案 ----------

def _c_tc(index, id=None, name=None, args=""):
    delta = SimpleNamespace(content=None, tool_calls=[
        SimpleNamespace(index=index, id=id,
                        function=SimpleNamespace(name=name, arguments=args))
    ])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def _c_text(text):
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


class _FakeCompletions:
    def __init__(self, script):
        self.script = iter(script)
        self.seen_messages = []

    def create(self, **kwargs):
        self.seen_messages.append(list(kwargs["messages"]))
        return iter(next(self.script))


def test_loop_model_recovers_after_denial(tmp_path):
    """剧本：模型要 write_file → 用户拒绝 → 模型读到拒绝文本，改用嘴回答。"""
    script = [
        [_c_tc(0, id="c1", name="write_file", args=_write_args(tmp_path))],
        [_c_text("好的，我不写文件了，直接告诉你内容")],
    ]
    bot = OpenAICompatibleBot()
    bot.client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(script)))
    GATE.confirm_handler = lambda name, args: "n"  # 用户全拒

    agent = Agent(bot=bot)
    reply = agent.run("把数据写进文件", Context(kwargs={"session_id": "perm"}))

    assert "不写文件" in reply.content
    second = bot.client.chat.completions.seen_messages[1]
    tool_msg = second[-1]
    assert tool_msg["role"] == "tool" and "拒绝" in tool_msg["content"]
    assert not (tmp_path / "x.txt").exists()
