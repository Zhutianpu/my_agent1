"""护甲三期：上下文溢出恢复（token 估算 + 主动道 + 被动道）。

全部离线：假 bot 抛带真实报错形状的异常，不烧钱。
报错原文抄自 CowAgent 注释里的 provider 真实样本。
"""

import pytest
from types import SimpleNamespace

from my_agent.agent.protocol.agent import Agent
from my_agent.agent.protocol.loop import run_loop, _EXPLICIT_RESPONSE_PROMPT
from my_agent.agent.protocol.overflow import (
    ContextOverflowError, is_context_overflow, overflow_budget, proactive_budget,
)
from my_agent.agent.tools.base_tool import ToolResult
from my_agent.config import conf
from my_agent.models.session_manager import SESSIONS, Session, estimate_text_tokens

# provider 真实报错样本（CowAgent agent_stream.py:2599 注释里的原样）
_REAL_ERROR = ("maximum context length is 1048576 tokens. However, you requested "
               "1276733 tokens (892733 in the messages, 384000 in the completion)")


class ScriptedBot:
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


class FakeMemory:
    def __init__(self):
        self.flushed = []

    def flush(self, discarded):
        self.flushed.append(list(discarded))
        return "蒸馏摘要"


@pytest.fixture(autouse=True)
def _pin_window(monkeypatch):
    # 真机 config 没有这个 key 之前走默认 128000；钉死防真机配置漂移
    monkeypatch.setitem(conf()._data, "model_context_window", 128000)


def _fill_turns(session, n, chars=800):
    """灌 n 轮 user+assistant（CJK 内容，估算 ≈ chars×1.5×2 / 轮）。"""
    for _ in range(n):
        session.add_query("问" * chars)
        session.add_reply("答" * chars)


# ---------- 估算 ----------

def test_estimator_cjk_vs_ascii():
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("你好") == int(2 * 1.5) + 1      # CJK ×1.5
    assert estimate_text_tokens("abcd") == int(4 * 0.25) + 1    # ASCII ÷4


def test_session_estimate_skips_system():
    s = Session("t")
    s.add_query("你好")
    assert s.estimate_tokens() == estimate_text_tokens("你好")


def test_session_estimate_counts_tool_calls():
    s = Session("t")
    s.add_query("hi")
    plain = s.estimate_tokens()
    s.messages.append({"role": "assistant", "content": "",
                       "tool_calls": [{"id": "c", "type": "function", "function":
                                       {"name": "read_file", "arguments": "{}"}}]})
    assert s.estimate_tokens() > plain


# ---------- 判型与预算 ----------

def test_classifier_real_and_negative():
    assert is_context_overflow(_REAL_ERROR)
    assert is_context_overflow("Error code: 400 - context_length_exceeded")
    assert not is_context_overflow("400 bad request: unknown model 'deepseek-no'")
    assert not is_context_overflow("rate limit exceeded, retry later")
    assert not is_context_overflow("")


def test_overflow_budget_parses_real_numbers():
    # (1048576 − 384000 − 1000) × 0.9
    assert overflow_budget(_REAL_ERROR, 1000) == int((1048576 - 384000 - 1000) * 0.9)


def test_overflow_budget_fallback_without_match(monkeypatch):
    monkeypatch.setitem(conf()._data, "model_context_window", 10000)
    # 抠不到 → 窗口 10000，completion 回退 20% = 2000
    assert overflow_budget("garbage", 1000) == int((10000 - 2000 - 1000) * 0.9)


def test_proactive_budget_is_80pct_minus_system(monkeypatch):
    monkeypatch.setitem(conf()._data, "model_context_window", 10000)
    assert proactive_budget(500) == 8000 - 500


# ---------- Session：token 裁剪 ----------

def test_discard_over_tokens_boundary_safe():
    s = Session("t")
    _fill_turns(s, 4, chars=400)  # 每轮 ≈ 400×1.5×2 = 1200 token
    before = len(s.messages)
    discarded, fits = s.discard_over_tokens(2600)  # 只容得下约 2 轮
    assert fits
    assert len(discarded) > 0 and len(s.messages) < before
    # 边界安全：剩下的第一条非 system 必须是 user，且没有孤儿 tool 消息
    rest = [m for m in s.messages if m.get("role") != "system"]
    assert rest[0]["role"] == "user"


def test_truncate_old_tool_results_before_discarding():
    s = Session("t")
    s.add_query("找文件")
    s.messages.append({"role": "assistant", "content": "",
                       "tool_calls": [{"id": "c1", "type": "function", "function":
                                       {"name": "read_file", "arguments": "{}"}}]})
    s.messages.append({"role": "tool", "tool_call_id": "c1", "content": "x" * 5000})
    s.add_reply("找到了")
    s.add_query("然后呢")  # 最后一轮不动
    big = estimate_text_tokens("x" * 5000)  # ≈1251
    budget = s.estimate_tokens() - big + 500  # 截断后达标、截断前不达标
    discarded, fits = s.discard_over_tokens(budget)
    assert fits and discarded == []  # 截断就够了，没丢整轮
    assert s._TRUNC_MARK in s.messages[3]["content"]  # [3] 才是 tool 结果
    assert len(s.messages[3]["content"]) < 600


def test_single_giant_turn_reports_not_fits():
    s = Session("t")
    s.add_query("爆" * 3000)  # 一轮就 ≈4500 token，超预算且无可丢
    discarded, fits = s.discard_over_tokens(2000)
    assert not fits and discarded == []
    assert len(s.messages) == 2  # system + 最后一轮：原样保留，没乱切


# ---------- 被动道：agent 级 ----------

def _overflow_exc(window=10000, completion=2000):
    return Exception(f"maximum context length is {window} tokens. However, you "
                     f"requested 99999 tokens (90000 in the messages, "
                     f"{completion} in the completion)")


def _ctx(events: list):
    from my_agent.bridge.context import Context, ContextType
    return Context(ContextType.TEXT, "x", kwargs={"on_event": events.append})


def test_agent_recovers_from_overflow():
    s = SESSIONS.build_session()
    _fill_turns(s, 3, chars=800)  # 3 轮 ≈ 7200 token，压缩后回预算内
    bot = ScriptedBot([_overflow_exc(), ("恢复后的回答", None)])
    mem = FakeMemory()
    events = []
    reply = Agent(bot=bot, system_prompt="你是测试", memory=mem).run("新问题", _ctx(events))
    assert reply.content == "恢复后的回答"
    assert bot.calls == 2  # 撞墙 → 压缩 → 重试一次成功
    assert any("撞墙" in e.get("data", {}).get("text", "") for e in events
               if e.get("type") == "notice")


def test_agent_overflow_distills_discarded():
    s = SESSIONS.build_session()
    _fill_turns(s, 3, chars=800)
    bot = ScriptedBot([_overflow_exc(), ("活过来了", None)])
    mem = FakeMemory()
    Agent(bot=bot, system_prompt="你是测试", memory=mem).run("新问题")
    assert len(mem.flushed) == 1 and len(mem.flushed[0]) > 0  # 裁掉的先保命
    session = SESSIONS.build_session()
    assert session.messages[1]["role"] == "system"  # 摘要注回头部
    assert session.messages[1]["content"].startswith(Session.SUMMARY_MARK)


def test_agent_double_overflow_apology_resets_memory_only():
    s = SESSIONS.build_session()
    _fill_turns(s, 2, chars=800)
    bot = ScriptedBot([_overflow_exc(), _overflow_exc()])  # 压缩后还撞
    reply = Agent(bot=bot, system_prompt="你是测试", memory=FakeMemory()).run("新问题")
    assert "重新描述" in reply.content
    assert bot.calls == 2  # 重试过一次，没有锤死循环
    session = SESSIONS.build_session()
    assert len(session.messages) == 1  # 内存清空（只剩 system 头），磁盘未动


def test_overflow_skips_fallback(monkeypatch):
    """溢出不该走模型 fallback：同样的上下文换备用模型照样撞。"""
    monkeypatch.setitem(conf()._data, "fallback_model", "gpt-whatever")
    SESSIONS.build_session()
    bot = ScriptedBot([_overflow_exc(), _overflow_exc()])
    events = []
    Agent(bot=bot, system_prompt="你是测试").run("新问题", _ctx(events))
    notices = [e.get("data", {}).get("text", "") for e in events
               if e.get("type") == "notice"]
    assert not any("备用模型" in t for t in notices)


# ---------- loop 级：催促注入的异常路径 ----------

class _FakeRegistry:
    def schemas(self):
        return [{"type": "function", "function":
                 {"name": "probe", "description": "d", "parameters": {}}}]

    def execute(self, name, arguments_json):
        return ToolResult.success("ok")


def test_empty_retry_prompt_popped_on_overflow():
    """空响应重试注入的催促是临时工——溢出异常路径也要 pop，不留垃圾。"""
    s = SESSIONS.build_session()
    s.add_query("干点活")
    bot = ScriptedBot([
        ("", [{"id": "c", "name": "probe", "arguments": "{}"}]),  # turn1 工具
        ("", None),            # turn2 空响应 → 注入催促再问
        _overflow_exc(),       # 催促那次 chat 撞墙
    ])
    with pytest.raises(ContextOverflowError):
        run_loop(bot=bot, session=s, on_event=lambda e: None,
                 max_turns=4, tools=_FakeRegistry())
    assert all(_EXPLICIT_RESPONSE_PROMPT not in (m.get("content") or "")
               for m in s.messages)
