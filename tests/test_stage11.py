"""阶段 11 验收测试：subagent 子代理（模板白名单 + 隔离 + 派发工具）。

全部离线：Bridge.bots 注入假 bot，子代理的循环在剧本里跑完。
"""

import json
from types import SimpleNamespace

from my_agent.agent.subagent.templates import (
    BLOCKED_TOOLS, EXPLORE, GENERAL_PURPOSE, TEMPLATES,
)
from my_agent.agent.tools import TOOLS
from my_agent.agent.tools.base_tool import BaseTool, ToolResult
from my_agent.agent.tools.subagent_tool import SubagentTool
from my_agent.bridge.bridge import Bridge
from my_agent.models.session_manager import SESSIONS


class S11Probe(BaseTool):
    name = "s11_probe"
    description = "阶段 11 测试探针"
    params = {"type": "object", "properties": {}}
    risk = "read"

    def execute(self, **kwargs):
        return ToolResult.success("探针结果")


TOOLS.register(S11Probe)


class ScriptedBot:
    """按剧本吐 (content, tool_calls)；剧本里放异常实例则抛。"""

    def __init__(self, script):
        self.script = list(script)

    def chat(self, messages, tools=None, on_delta=None):
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        content, tool_calls = step
        return SimpleNamespace(content=content, tool_calls=tool_calls, usage=None)


def _inject_bot(bot):
    Bridge().bots["chat"] = bot  # get_bot 命中缓存，子代理拿到的就是它


def teardown_function():
    Bridge().bots.clear()
    SESSIONS.sessions.clear()


# ---------- 模板白名单（P2 的缝兑现） ----------

def test_explore_is_read_only():
    names = EXPLORE.select_tool_names(list(TOOLS._tools))
    assert "read_file" in names and "memory_search" in names
    assert "write_file" not in names and "run_command" not in names
    assert "edit_file" not in names


def test_general_purpose_gets_all_minus_blocked():
    names = GENERAL_PURPOSE.select_tool_names(list(TOOLS._tools))
    assert "write_file" in names and "run_command" in names


def test_iron_rule_no_template_has_dispatch():
    """铁律：任何模板都拿不到 subagent——子代理结构上不可能套娃。"""
    assert "subagent" in BLOCKED_TOOLS
    for t in TEMPLATES.values():
        assert "subagent" not in t.select_tool_names(list(TOOLS._tools))


def test_subset_registry_mechanics():
    sub = TOOLS.subset(["read_file", "s11_probe"])
    names = [s["function"]["name"] for s in sub.schemas()]
    assert sorted(names) == ["read_file", "s11_probe"]
    assert sub.get("write_file") is None
    r = sub.execute("s11_probe", "{}")
    assert r.status == "success"  # 子集注册表照常能执行


# ---------- 派发工具 ----------

def test_dispatch_single_task_returns_summary():
    _inject_bot(ScriptedBot([("调查结论：答案是 42", None)]))
    r = TOOLS.execute("subagent", json.dumps({"goal": "调查答案"}))
    assert r.status == "success"
    results = json.loads(r.result)["results"]
    assert results[0]["status"] == "completed"
    assert "42" in results[0]["summary"]
    assert results[0]["subagent_type"] == "general-purpose"  # 缺省角色


def test_dispatch_isolation_no_history_no_leak():
    """隔离验证：子代理 session 用完即弃——柜子清了，磁盘没留 jsonl。"""
    _inject_bot(ScriptedBot([("干完了", None)]))
    SESSIONS.persist = True  # 故意开持久化：persist_session=False 必须挡住落盘
    try:
        TOOLS.execute("subagent", json.dumps({"goal": "干活"}))
        leaked = [k for k in SESSIONS.sessions if str(k[1]).startswith("subagent_")]
        assert leaked == []
        from my_agent.config import ROOT
        files = list((ROOT / "workspaces" / "default" / "sessions").glob("subagent_*.jsonl"))
        assert files == []  # 磁盘上一个子代理会话文件都不许有
    finally:
        SESSIONS.persist = False


def test_dispatch_validation_errors():
    tool = SubagentTool()
    assert tool.execute(goal="").status == "error"                       # 空 goal
    assert tool.execute(goal="x", subagent_type="不存在").status == "error"  # 未知类型
    too_many = {"tasks": [{"goal": f"任务{i}"} for i in range(4)]}
    assert tool.execute(**too_many).status == "error"                    # 超过 3 个


def test_dispatch_all_failed_returns_fail():
    """子代理全灭 → 工具级 fail（防父 agent 拿不存在的结论去汇报）。"""
    _inject_bot(ScriptedBot([RuntimeError("模型炸了")]))
    r = TOOLS.execute("subagent", json.dumps({"goal": "必败任务"}))
    assert r.status == "error"
    assert json.loads(r.result)["results"][0]["status"] == "failed"


def test_child_uses_tools_and_budget_halved(monkeypatch):
    """子代理能跑工具循环；预算 = 父的一半（8 → 4）。"""
    monkeypatch.setenv("AGENT_MAX_TURNS", "8")
    infinite = ScriptedBot([])
    infinite.chat = lambda messages, tools=None, on_delta=None: SimpleNamespace(
        content="", usage=None,
        tool_calls=[{"id": "c", "name": "s11_probe", "arguments": "{}"}],
    )
    _inject_bot(infinite)
    r = TOOLS.execute("subagent", json.dumps({"goal": "永远跑不完的任务"}))
    results = json.loads(r.result)["results"]
    # 预算规则 max(6, parent//2)：parent=8 → 6（保底生效；真机教训：
    # 裸减半只剩 4，explore 查个文件就饿死）
    assert "最大工具轮数 6" in results[0]["summary"]


def test_dispatch_tasks_list_in_order():
    """多任务：按下单顺序返回结果，类型各自路由。"""
    _inject_bot(ScriptedBot([("查完了", None), ("写完了", None)]))
    r = TOOLS.execute("subagent", json.dumps({"tasks": [
        {"goal": "查资料", "subagent_type": "explore"},
        {"goal": "写文件"},
    ]}))
    results = json.loads(r.result)["results"]
    assert [x["subagent_type"] for x in results] == ["explore", "general-purpose"]
    assert "查完了" in results[0]["summary"] and "写完了" in results[1]["summary"]
