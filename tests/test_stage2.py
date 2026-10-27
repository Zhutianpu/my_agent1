"""阶段 2 验收测试（阶段 4 契约修订版）：Bridge 路由 + terminal channel 双向流。

FakeBot 现在实现 chat()——纯生成器，历史由 Agent 层记账。
"""

import builtins

from my_agent.bridge.bridge import Bridge
from my_agent.bridge.context import Context, ContextType
from my_agent.bridge.reply import ReplyType
from my_agent.channel.channel import ChatChannel
from my_agent.channel.terminal import TerminalChannel
from my_agent.models.bot import Bot, BotResponse
from my_agent.models.session_manager import SESSIONS
from my_agent.common import const


class FakeBot(Bot):
    def __init__(self):
        self.calls = []

    def chat(self, messages, tools=None, on_delta=None):
        q = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        self.calls.append(q)
        text = f"回声: {q}"
        if on_delta:
            on_delta(text)
        return BotResponse(content=text)


def setup_function():
    SESSIONS.sessions.clear()
    Bridge().reset_bot()
    Bridge().bots["chat"] = FakeBot()


def fakebot() -> FakeBot:
    return Bridge().bots["chat"]


def test_bridge_lazy_cache():
    b = Bridge()
    assert b.get_bot("chat") is b.get_bot("chat")


def test_bridge_routes_query_to_reply():
    r = Bridge().fetch_agent_reply("你好", Context(ContextType.TEXT, "你好"))
    assert r.type == ReplyType.TEXT
    assert fakebot().calls == ["你好"]


def test_produce_calls_send():
    class RecordingChannel(ChatChannel):
        def __init__(self):
            self.sent = []

        def send(self, reply, context):
            self.sent.append((reply, context))

    ch = RecordingChannel()
    ctx = Context(ContextType.TEXT, "测试", kwargs={"session_id": "s"})
    ch.produce(ctx)
    assert len(ch.sent) == 1
    reply, got_ctx = ch.sent[0]
    assert reply.content == "回声: 测试"
    assert got_ctx is ctx


def test_terminal_repl_flow(capsys, monkeypatch):
    """端到端（假键盘）：两轮对话 + #reset + #exit。"""
    inputs = iter(["你好", "第二句", "#reset", "#exit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))

    TerminalChannel(session_id="test").startup()

    out = capsys.readouterr().out
    assert "回声: 你好" in out
    assert "回声: 第二句" in out
    assert "对话已清空" in out
    assert fakebot().calls == ["你好", "第二句"]  # 命令不送给模型


def test_unknown_hash_command_intercepted(capsys, monkeypatch):
    """# 开头但不认识的命令：拦截提醒，不送给模型（真机抓到的 #rest typo）。"""
    inputs = iter(["#rest", "#exit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))

    TerminalChannel(session_id="test2").startup()

    out = capsys.readouterr().out
    assert "未知命令 #rest" in out
    assert fakebot().calls == []


def test_terminal_multi_turn_history(capsys, monkeypatch):
    """同一进程内多轮：柜子活着，历史累积——补上 ask.py 跨进程失忆那一课。"""
    inputs = iter(["第一句", "第二句", "#exit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))

    TerminalChannel(session_id="multi").startup()

    session = SESSIONS.build_session("multi", const.DEFAULT_AGENT_ID)
    assert [m["role"] for m in session.messages] == [
        "system", "user", "assistant", "user", "assistant",
    ]
