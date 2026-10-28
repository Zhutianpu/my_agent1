"""循环护甲二期测试：空响应重试 / Ctrl+C 取消 / 模型 fallback。

全部离线：ArmorBot 按剧本吐 (content, tool_calls) 或抛异常；
假工具注册进真 TOOLS（名字 armor_ 开头，不撞内建）。
"""

import json
from types import SimpleNamespace

from my_agent.agent.protocol.agent import Agent
from my_agent.agent.protocol.loop import (
    _EMPTY_FALLBACK, _EXPLICIT_RESPONSE_PROMPT, _INTERRUPT_NOTE, run_loop,
)
from my_agent.agent.tools import TOOLS
from my_agent.agent.tools.base_tool import BaseTool, ToolResult
from my_agent.bridge.context import Context
from my_agent.bridge.reply import ReplyType
from my_agent.channel.terminal import TerminalRenderer
from my_agent.models.session_manager import SESSIONS


# ---------- 假 bot 与假工具 ----------

class ArmorBot:
    """剧本：每步是 (content, tool_calls) 元组，或一个要抛的异常实例。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat(self, messages, tools=None, on_delta=None):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        content, tool_calls = step
        return SimpleNamespace(content=content, tool_calls=tool_calls, usage=None)


class ArmorTool(BaseTool):
    name = "armor_fake"
    description = "护甲测试用假工具"
    params = {"type": "object", "properties": {}}
    risk = "read"

    def execute(self, **kwargs):
        return ToolResult.success("假工具结果")


class ArmorBoomTool(BaseTool):
    name = "armor_boom"
    description = "执行时模拟 Ctrl+C"
    params = {"type": "object", "properties": {}}
    risk = "read"

    def execute(self, **kwargs):
        raise KeyboardInterrupt


TOOLS.register(ArmorTool)
TOOLS.register(ArmorBoomTool)


def _tc(name, call_id="c1"):
    return {"id": call_id, "name": name, "arguments": json.dumps({})}


def _setup(query="问"):
    session = SESSIONS.build_session("armor_s", "armor_test")
    session.add_query(query)
    events = []
    return session, events


def _run(bot, session, events, max_turns=5):
    return run_loop(bot=bot, session=session, on_event=events.append, max_turns=max_turns)


def teardown_function():
    SESSIONS.sessions.clear()


# ---------- 1. 空响应重试 ----------

def test_empty_retry_after_tools():
    """工具跑完模型沉默 → 催促一次 → 出答案；催促不进历史。"""
    bot = ArmorBot([("", [_tc("armor_fake")]), ("", None), ("最终答案", None)])
    session, events = _setup()
    assert _run(bot, session, events) == "最终答案"
    assert bot.calls == 3
    # 催促用完 pop：持久历史里找不到它
    assert all(m.get("content") != _EXPLICIT_RESPONSE_PROMPT for m in session.messages)
    assert session.messages[-1] == {"role": "assistant", "content": "最终答案"}


def test_first_turn_empty_no_retry():
    """首轮就空（没跑过工具）→ 不催促，直接兜底文案。"""
    bot = ArmorBot([("", None)])
    session, events = _setup()
    assert _run(bot, session, events) == _EMPTY_FALLBACK
    assert bot.calls == 1  # 没有第二次调用


def test_retry_still_empty_fallback():
    """催促后还是空 → 兜底文案；催促同样被 pop。"""
    bot = ArmorBot([("", [_tc("armor_fake")]), ("", None), ("", None)])
    session, events = _setup()
    assert _run(bot, session, events) == _EMPTY_FALLBACK
    assert bot.calls == 3
    assert all(m.get("content") != _EXPLICIT_RESPONSE_PROMPT for m in session.messages)


def test_retry_returns_tool_calls_falls_through():
    """催促后模型改给工具订单 → 不 break，落回工具路径继续跑。"""
    bot = ArmorBot([
        ("", [_tc("armor_fake", "c1")]),   # turn 1：跑工具
        ("", None),                         # turn 2：沉默 → 触发催促
        ("", [_tc("armor_fake", "c2")]),   # 催促回应：又给了订单
        ("绕一圈的答案", None),              # turn 3：收工
    ])
    session, events = _setup()
    assert _run(bot, session, events) == "绕一圈的答案"
    assert bot.calls == 4
    tools_run = [e["data"]["tool_name"] for e in events if e["type"] == "tool_execution_end"]
    assert tools_run == ["armor_fake", "armor_fake"]


# ---------- 2. Ctrl+C 取消 ----------

def test_ctrlc_during_chat_graceful():
    """chat 时按 Ctrl+C → 循环接住，补 assistant 中断条，历史完整。"""
    bot = ArmorBot([KeyboardInterrupt()])
    session, events = _setup()
    assert _run(bot, session, events) == _INTERRUPT_NOTE
    assert session.messages[-1] == {"role": "assistant", "content": _INTERRUPT_NOTE}
    assert any(e["type"] == "notice" for e in events)


def test_ctrlc_mid_tool_keeps_pairing():
    """工具执行到一半中断：剩余 tool_call 用"已中断"结果补齐——
    每个 tool_call 都必须有配对 tool result（API 硬要求）。"""
    bot = ArmorBot([("", [_tc("armor_fake", "ok1"), _tc("armor_boom", "boom2"),
                          _tc("armor_fake", "never3")])])
    session, events = _setup()
    assert _run(bot, session, events) == _INTERRUPT_NOTE
    assert bot.calls == 1  # 中断后没有再回到模型
    assistant = [m for m in session.messages if m["role"] == "assistant"][0]
    results = {m["tool_call_id"]: m["content"] for m in session.messages if m["role"] == "tool"}
    assert results["ok1"] == "假工具结果"          # 跑完的保留真结果
    assert results["boom2"] == "（执行被用户中断）"  # 中断当场补
    assert results["never3"] == "（执行被用户中断）"  # 没跑的也要补（配对完整）
    assert len(results) == len(assistant["tool_calls"])


def test_agent_level_ctrlc_returns_reply_not_crash():
    """agent.run 层：中断不杀应用，返回正常 Reply 且历史落盘。"""
    agent = Agent(bot=ArmorBot([KeyboardInterrupt()]))
    reply = agent.run("问", Context(kwargs={"session_id": "s", "agent_id": "armor_test"}))
    assert reply.type == ReplyType.TEXT and "中断" in reply.content


# ---------- 3. 模型 fallback ----------

def test_fallback_switch_on_model_error(monkeypatch):
    """主模型抛错 + 配了 fallback_model → 粘性切备用，重试出答案。"""
    monkeypatch.setenv("FALLBACK_MODEL", "backup-x")
    backup = ArmorBot([("备用模型的答案", None)])
    monkeypatch.setattr("my_agent.models.bot_factory.create_bot",
                        lambda model=None: backup)
    main = ArmorBot([RuntimeError("主模型 500")])
    session, events = _setup()
    assert _run(main, session, events) == "备用模型的答案"
    assert main.calls == 1 and backup.calls == 1
    notices = [e["data"]["text"] for e in events if e["type"] == "notice"]
    assert any("backup-x" in n for n in notices)


def test_no_fallback_configured_propagates(monkeypatch):
    """没配 fallback：异常原样上去，agent.run 兜底成 error Reply。"""
    monkeypatch.delenv("FALLBACK_MODEL", raising=False)
    agent = Agent(bot=ArmorBot([RuntimeError("挂了")]))
    reply = agent.run("问", Context(kwargs={"session_id": "s", "agent_id": "armor_test"}))
    assert reply.type == ReplyType.ERROR and "挂了" in reply.content


# ---------- 旁路：终端渲染 notice 事件 ----------

def test_terminal_renders_notice(capsys):
    TerminalRenderer().handle_event({"type": "notice", "data": {"text": "切换提示"}})
    assert "切换提示" in capsys.readouterr().out
