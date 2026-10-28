"""阶段 10 验收测试：web channel（FastAPI + SSE + 异步权限闸）。

全部离线：TestClient（httpx）+ ScriptedBot 假 agent，不起 uvicorn、不联网。
核心验证：三问第 3 条——换 channel 不动 agent 核心，事件流原样复用。
"""

import queue
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from my_agent.agent.protocol.agent import Agent
from my_agent.bridge.bridge import Bridge
from my_agent.channel.factory import create_channel
from my_agent.channel.terminal import TerminalChannel
from my_agent.channel.web.web_channel import (
    HUB, WebChannel, _sse_lines, build_app, resolve_confirm, web_confirm,
)
from my_agent.common import const


class ScriptedBot:
    """按剧本依次吐 content 的假 bot（与 test_stage7 同款，不流式）。"""

    def __init__(self, script):
        self.script = iter(script)

    def chat(self, messages, tools=None, on_delta=None):
        return SimpleNamespace(content=next(self.script), tool_calls=None, usage=None)


def _drain_turn(q, timeout=5):
    """捞一轮对话的全部事件：agent_end 之后还要再收——
    send() 的兜底 message_update 是在 agent_end 之后才发布的
    （run 发完事件才 return，produce 链上 send 在最后）。"""
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ev = q.get(timeout=max(0.05, deadline - time.monotonic()))
        except queue.Empty:
            break
        events.append(ev)
        if ev.get("type") == "agent_end":
            # agent_end 到了：再给 send 兜底 0.5s，收不到就算了（流式场景没有兜底）
            while True:
                try:
                    events.append(q.get(timeout=0.5))
                except queue.Empty:
                    return events
    return events


def _inject_fake_agent(*replies):
    agent = Agent(bot=ScriptedBot(list(replies)))
    Bridge()._agents[const.DEFAULT_AGENT_ID] = agent
    return agent


def teardown_function():
    Bridge()._agents.clear()


# ---------- channel 工厂 ----------

def test_factory_terminal_via_config(monkeypatch):
    # 教训：不能假设"默认 terminal"——真机 config.json 可能已改成 web。
    # env 优先级高于 config.json，用它把配置钉死。
    monkeypatch.setenv("CHANNEL", "terminal")
    assert isinstance(create_channel(), TerminalChannel)


def test_factory_web_via_config(monkeypatch):
    monkeypatch.setenv("CHANNEL", "web")  # conf().get 环境变量优先
    assert isinstance(create_channel(), WebChannel)


# ---------- SSE 产线与事件枢纽 ----------

def test_sse_lines_format_and_order():
    q = queue.Queue()
    gen = _sse_lines(q)
    assert "已连接" in next(gen)  # 开场 notice
    q.put({"type": "notice", "data": {"text": "你好"}})
    line = next(gen)
    assert line.startswith("data: ") and line.endswith("\n\n")
    assert "你好" in line  # ensure_ascii=False：中文不转义


def test_sse_heartbeat_on_idle():
    q = queue.Queue()
    gen = _sse_lines(q, heartbeat=0.05)
    next(gen)  # 跳过开场
    assert next(gen) == ": ping\n\n"  # 队列空 → 心跳保活


def test_hub_multicast_and_unsubscribe():
    qa, qb = HUB.subscribe(), HUB.subscribe()
    HUB.publish({"type": "notice", "data": {"text": "广播"}})
    assert qa.get(timeout=1)["data"]["text"] == "广播"
    assert qb.get(timeout=1)["data"]["text"] == "广播"
    HUB.unsubscribe(qa)
    HUB.publish({"type": "notice", "data": {"text": "第二条"}})
    assert qb.get(timeout=1)["data"]["text"] == "第二条"
    assert qa.empty()  # 退订后收不到
    HUB.unsubscribe(qb)


# ---------- HTTP 端点 ----------

def test_index_page_served():
    client = TestClient(build_app(WebChannel()))
    r = client.get("/")
    assert r.status_code == 200 and "my-agent" in r.text


def test_chat_end_to_end_events_flow():
    """三问第 3 条的证据：假 agent 经 web channel 跑完一轮，
    事件（agent_start→message_update→agent_end）原样流到订阅者。"""
    _inject_fake_agent("你好呀")
    client = TestClient(build_app(WebChannel()))
    q = HUB.subscribe()
    try:
        r = client.post("/api/chat", json={"text": "嗨"})
        assert r.json()["ok"]
        events = _drain_turn(q)
        types = [e["type"] for e in events]
        assert types[0] == "agent_start"
        # ScriptedBot 不流式 → send() 兜底把整段答复补推成 message_update
        deltas = [e["data"]["delta"] for e in events if e["type"] == "message_update"]
        assert "你好呀" in "".join(deltas)
    finally:
        HUB.unsubscribe(q)


def test_commands_reset_and_unknown():
    client = TestClient(build_app(WebChannel()))
    q = HUB.subscribe()
    try:
        assert client.post("/api/chat", json={"text": "#reset"}).json()["ok"]
        ev = q.get(timeout=5)
        assert ev["type"] == "notice" and "已清空" in ev["data"]["text"]
        assert client.post("/api/chat", json={"text": "#foo"}).json()["ok"]
        ev = q.get(timeout=5)
        assert "未知命令" in ev["data"]["text"]
    finally:
        HUB.unsubscribe(q)


# ---------- 异步权限闸（阶段 6 的缝兑现） ----------

def test_web_confirm_roundtrip():
    client = TestClient(build_app(WebChannel()))
    q = HUB.subscribe()
    try:
        result = []
        t = threading.Thread(
            target=lambda: result.append(
                web_confirm("run_command", {"command": "ls"}, timeout=5)))
        t.start()
        ev = q.get(timeout=5)  # 浏览器端先收到确认请求
        assert ev["type"] == "confirm_request"
        assert ev["data"]["tool_name"] == "run_command"
        client.post("/api/confirm", json={"answer": "y"})
        t.join(timeout=5)
        assert result == ["y"]
    finally:
        HUB.unsubscribe(q)


def test_web_confirm_default_deny_on_timeout():
    # 没人点 = 拒绝（默认安全），不永久卡死 agent 线程
    assert web_confirm("write_file", {"path": "x"}, timeout=0.05) == "n"


def test_resolve_confirm_without_pending_is_noop():
    resolve_confirm("y")  # 没有 pending 时不炸
