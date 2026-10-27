"""阶段 3 验收测试（阶段 4 契约修订版）：工具层 + 工具循环（流式假客户端）。

流式 chunk 剧本：tool_calls 是分块到达的（id/名字/参数碎片），
bot.chat 负责按 index 拼回完整订单——这正是本次要验证的事。
"""

import json
from types import SimpleNamespace

from my_agent.agent.tools import TOOLS  # 触发内建工具注册
from my_agent.agent.protocol.agent import Agent
from my_agent.bridge.context import Context
from my_agent.models.openai_compatible_bot import OpenAICompatibleBot
from my_agent.models.session_manager import SESSIONS


def setup_function():
    SESSIONS.sessions.clear()


# ---------- 工具单体 ----------

def test_write_then_read_roundtrip(tmp_path):
    f = tmp_path / "a.txt"
    r = TOOLS.execute("write_file", json.dumps({"path": str(f), "content": "hello"}))
    assert r.status == "success"
    r = TOOLS.execute("read_file", json.dumps({"path": str(f)}))
    assert r.status == "success" and r.result == "hello"


def test_read_missing_file_is_error_text():
    r = TOOLS.execute("read_file", json.dumps({"path": "不存在.txt"}))
    assert r.status == "error" and "不存在" in r.result


def test_read_pagination(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("\n".join(str(i) for i in range(100)), encoding="utf-8")
    r = TOOLS.execute("read_file", json.dumps({"path": str(f), "offset": 10, "limit": 5}))
    assert r.result.splitlines() == ["9", "10", "11", "12", "13"]


def test_ls(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "f.py").write_text("x", encoding="utf-8")
    r = TOOLS.execute("ls", json.dumps({"path": str(tmp_path)}))
    assert "[dir] sub" in r.result and "[file] f.py" in r.result


def test_run_command_and_danger_block():
    r = TOOLS.execute("run_command", json.dumps({"command": "echo hello"}))
    assert r.status == "success" and "hello" in r.result
    r = TOOLS.execute("run_command", json.dumps({"command": "rm -rf /"}))
    assert r.status == "error" and "拦截" in r.result


def test_search_files(tmp_path):
    (tmp_path / "a.py").write_text("def 目标函数():\n    pass\n", encoding="utf-8")
    r = TOOLS.execute("search_files", json.dumps({"pattern": "目标函数", "path": str(tmp_path)}))
    assert "a.py:1" in r.result


def test_manager_contracts():
    names = [s["function"]["name"] for s in TOOLS.schemas()]
    assert {"read_file", "write_file", "ls", "run_command", "search_files"} <= set(names)
    assert TOOLS.execute("没有的工具", "{}").status == "error"
    assert TOOLS.execute("read_file", "{坏json").status == "error"


# ---------- 工具循环（流式假客户端剧本） ----------

def _c_text(text):
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def _c_tc(index, id=None, name=None, args=""):
    """一块工具订单碎片。真实流式里 id/名字/参数是分块到的。"""
    delta = SimpleNamespace(content=None, tool_calls=[
        SimpleNamespace(index=index, id=id,
                        function=SimpleNamespace(name=name, arguments=args))
    ])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


class FakeCompletions:
    def __init__(self, script):
        self.script = iter(script)
        self.seen_messages = []

    def create(self, **kwargs):
        self.seen_messages.append(list(kwargs["messages"]))
        return iter(next(self.script))


class FakeClient:
    def __init__(self, script):
        self.chat = SimpleNamespace(completions=FakeCompletions(script))


def test_tool_loop_two_turns_streaming(tmp_path):
    """剧本：第一轮模型下单（参数故意碎成两块）→ 工具执行回填 → 第二轮流式回答。"""
    f = tmp_path / "note.txt"
    f.write_text("文件的秘密内容", encoding="utf-8")

    args = json.dumps({"path": str(f)})
    half = len(args) // 2
    script = [
        [_c_tc(0, id="call_1", name="read_file", args=args[:half]),
         _c_tc(0, args=args[half:])],          # 第一幕：碎片订单
        [_c_text("读完了"), _c_text("，内容是秘密")],  # 第二幕：流式答案
    ]
    bot = OpenAICompatibleBot()
    bot.client = FakeClient(script)
    agent = Agent(bot=bot)

    events = []
    ctx = Context(kwargs={"session_id": "loop", "on_event": lambda e: events.append(e)})
    reply = agent.run("帮我读一下 note.txt", ctx)

    assert reply.content == "读完了，内容是秘密"
    types = [e["type"] for e in events]
    assert "tool_execution_start" in types and "tool_execution_end" in types
    # 文本碎片经过 on_event 流了出去
    deltas = [e["data"]["delta"] for e in events if e["type"] == "message_update"]
    assert "".join(deltas) == "读完了，内容是秘密"
    # 第二次调用时 messages 里已有 tool 回执
    second = bot.client.chat.completions.seen_messages[1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]
    assert "文件的秘密内容" in second[3]["content"]


def test_loop_turn_cap():
    """模型一直下单不停 → 达到轮数上限强制收尾，不死循环。"""
    script = [[_c_tc(0, id=f"c{i}", name="ls", args="{}")] for i in range(99)]
    bot = OpenAICompatibleBot()
    bot.client = FakeClient(script)
    agent = Agent(bot=bot)

    reply = agent.run("不停地 ls", Context(kwargs={"session_id": "cap"}))
    assert "最大工具轮数" in reply.content
