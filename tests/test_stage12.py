"""P2 验收测试：多 agent（花名册 + 派单 + 信箱）。

全部离线：Bridge._agents 注入假同事，conf()._data 钉死花名册配置
（真机 config.json 有没有 agents 都不影响测试——同 test_factory 的教训）。
"""

import json
from types import SimpleNamespace

import pytest

from my_agent.agent import mailbox
from my_agent.agent.protocol import agent as agent_mod
from my_agent.agent.protocol.agent import Agent
from my_agent.agent.roster import load_roster
from my_agent.agent.tools import TOOLS
from my_agent.agent.tools.agent_delegate import AgentDelegateTool
from my_agent.agent.tools.agent_message import AgentMessageTool
from my_agent.bridge.bridge import Bridge
from my_agent.config import conf
from my_agent.models.session_manager import SESSIONS


class ScriptedBot:
    """按剧本吐 (content, tool_calls)；顺手记下每场对话和拿到的工具表。"""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []  # 每场 chat 的 messages
        self.tools_seen = None

    def chat(self, messages, tools=None, on_delta=None):
        self.seen.append(list(messages))
        self.tools_seen = tools
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        content, tool_calls = step
        return SimpleNamespace(content=content, tool_calls=tool_calls, usage=None)


@pytest.fixture(autouse=True)
def _clean_p2_state():
    yield
    Bridge().bots.clear()
    Bridge()._agents.clear()
    agent_mod._run_local.stack = []


def _set_roster(monkeypatch, agents):
    monkeypatch.setitem(conf()._data, "agents", agents)


def _fake_peer(agent_id="builder", script=None):
    """把假同事塞进 Bridge 装配缓存：跳过真装配（不碰真 workspaces）。"""
    bot = ScriptedBot(script if script is not None else [("结论带回", None)])
    Bridge()._agents[agent_id] = SimpleNamespace(
        bot=bot, system_prompt=f"{agent_id} 的人设", max_turns=8, memory=None)
    return bot


# ---------- 花名册 ----------

def test_roster_default_always_present(monkeypatch):
    _set_roster(monkeypatch, [])
    roster = load_roster()
    assert list(roster) == ["default"]


def test_roster_parses_entries(monkeypatch):
    _set_roster(monkeypatch, [
        {"id": "builder", "name": "建造者", "description": "写文件写代码"},
        {"id": "bad id!"},                      # 非法 id → 跳过
        {"id": "default", "name": "冒充者"},     # 占 default → 跳过
        {"id": "builder", "name": "重复"},       # 重复 id → 跳过
    ])
    roster = load_roster()
    assert sorted(roster) == ["builder", "default"]
    assert roster["builder"].name == "建造者"
    assert roster["default"].name == "默认助手"  # 没被冒充


# ---------- 派单工具 ----------

def test_delegate_schema_lists_roster(monkeypatch):
    """花名册现读现编进说明书——模型看着名单挑人。"""
    _set_roster(monkeypatch, [{"id": "builder", "name": "建造者", "description": "写文件"}])
    desc = TOOLS.get("agent_delegate").schema()["function"]["description"]
    assert "builder（建造者）" in desc and "写文件" in desc


def test_delegate_unknown_agent(monkeypatch):
    _set_roster(monkeypatch, [])
    r = AgentDelegateTool().execute(agent_id="ghost", task="干啥")
    assert r.status == "error" and "在册的" in r.result


def test_delegate_success(monkeypatch):
    """派单全链路：包装任务 → 同事跑完 → 结论带回；同事的工具表里没有派单工具。"""
    _set_roster(monkeypatch, [{"id": "builder", "name": "建造者"}])
    peer_bot = _fake_peer(script=[("诗写好了：床前明月光", None)])
    r = AgentDelegateTool().execute(agent_id="builder", task="写一首五言绝句")
    assert r.status == "success" and "床前明月光" in r.result
    # delegated_prompt：任务被包过，且声明"不会直接给用户看"
    prompt = peer_bot.seen[0][-1]["content"]
    assert "写一首五言绝句" in prompt and "委托" in prompt and "转述" in prompt
    # 结构级防循环（阶段 11 同一招）：同事想再派单都没家伙
    peer_tool_names = [s["function"]["name"] for s in peer_bot.tools_seen]
    assert "agent_delegate" not in peer_tool_names
    # 正向断言（真机教训）：只断言"没有坏事"漏过生成器耗尽 bug——
    # subset 把 10 件裁到只剩 read_file，反向断言照样全绿
    assert "write_file" in peer_tool_names and "run_command" in peer_tool_names
    # 委托进了同事的主会话——它记得住这次协作（与 subagent 用完即弃相反）
    assert ("builder", "default") in SESSIONS.sessions


def test_delegate_refuses_running_agent(monkeypatch):
    """不能派给正在干活的 agent：两个 run 嵌套同一 session，历史绞麻花。"""
    _set_roster(monkeypatch, [{"id": "builder", "name": "建造者"}])
    monkeypatch.setattr(agent_mod._run_local, "stack", [("builder", "default")])
    r = AgentDelegateTool().execute(agent_id="builder", task="套娃吗")
    assert r.status == "error" and "正在干活" in r.result


def test_delegate_peer_error_becomes_tool_failure(monkeypatch):
    """ERROR 是 Reply 不是异常（阶段 11 的教训）：同事炸了要翻译成工具失败。"""
    _set_roster(monkeypatch, [{"id": "builder", "name": "建造者"}])
    _fake_peer(script=[RuntimeError("模型炸了")])
    r = AgentDelegateTool().execute(agent_id="builder", task="干点啥")
    assert r.status == "error" and "builder" in r.result


def test_delegate_full_loop_with_attribution(monkeypatch):
    """完整循环：父 agent 派单，栈顶署名 default，结论进父上下文被转述。"""
    _set_roster(monkeypatch, [{"id": "builder", "name": "建造者"}])
    peer_bot = _fake_peer(script=[("查完了：3 处", None)])
    parent_bot = ScriptedBot([
        ("", [{"id": "c1", "name": "agent_delegate",
               "arguments": json.dumps({"agent_id": "builder", "task": "数数几处"})}]),
        ("同事说 3 处", None),
    ])
    reply = Agent(bot=parent_bot, max_turns=4).run("让 builder 数数")
    assert reply.content == "同事说 3 处"
    assert "来自 agent「default」的委托" in peer_bot.seen[0][-1]["content"]


# ---------- 信箱 ----------

def test_mailbox_roundtrip():
    mailbox.send("builder", "default", "记得喝水")
    mails = mailbox.drain("builder")
    assert len(mails) == 1 and mails[0]["text"] == "记得喝水"
    assert mailbox.drain("builder") == []  # 签收即清空


def test_agent_run_drains_mailbox():
    """上线先签收：留言并进本轮用户消息，模型一次看全。"""
    mailbox.send("default", "builder", "周报格式改了")
    bot = ScriptedBot([("知道了", None)])
    Agent(bot=bot).run("你好")
    user_msg = bot.seen[0][-1]["content"]
    assert "信箱" in user_msg and "周报格式改了" in user_msg and "你好" in user_msg


def test_agent_message_tool(monkeypatch):
    _set_roster(monkeypatch, [{"id": "builder", "name": "建造者"}])
    r = AgentMessageTool().execute(agent_id="builder", message="明早交接", from_agent="default")
    assert r.status == "success" and "签收" in r.result
    mails = mailbox.drain("builder")
    assert mails[0]["from"] == "default" and mails[0]["text"] == "明早交接"


def test_agent_message_refuses_self(monkeypatch):
    monkeypatch.setattr(agent_mod._run_local, "stack", [("default", "default")])
    r = AgentMessageTool().execute(agent_id="default", message="自言自语")
    assert r.status == "error" and "没意义" in r.result


# ---------- 回归：subset 生成器耗尽（P2 真机抓的） ----------

def test_subset_accepts_generator():
    """生成器只能消费一次：set() 写在推导式 if 里会第一次迭代就把它耗尽，
    白名单裁到只剩第一个工具（真机上 builder 派单后只剩 read_file）。"""
    sub = TOOLS.subset(n for n in ("read_file", "ls", "run_command") if n != "ls")
    assert sorted(sub._tools) == ["read_file", "run_command"]
