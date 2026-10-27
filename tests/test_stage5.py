"""阶段 5 验收测试：workspace + prompt 编译器 + 装配间 + 两个新工具。

不烧钱：全部用 tmp_path 假 workspace 和不联网的假 bot。
"""

import json
from types import SimpleNamespace

from my_agent.agent.initializer import initialize_agent
from my_agent.agent.prompt import (
    ContextFile, build_system_prompt, ensure_workspace, load_context_files,
)
from my_agent.agent.tools import TOOLS
from my_agent.bridge.bridge import Bridge
from my_agent.bridge.context import Context
from my_agent.agent.protocol.agent import Agent
from my_agent.models.session_manager import SESSIONS


def setup_function():
    SESSIONS.sessions.clear()


# ---------- workspace ----------

def test_ensure_workspace_creates_templates(tmp_path):
    ws = ensure_workspace(tmp_path / "ws")
    assert (ws / "AGENT.md").exists()
    assert (ws / "USER.md").exists()
    assert (ws / "MEMORY.md").exists()
    assert (ws / "memory").is_dir()


def test_ensure_workspace_never_overwrites(tmp_path):
    ws = ensure_workspace(tmp_path / "ws")
    (ws / "AGENT.md").write_text("我的名字是阿牛", encoding="utf-8")
    ensure_workspace(ws)  # 再跑一遍
    assert (ws / "AGENT.md").read_text(encoding="utf-8") == "我的名字是阿牛"


def test_load_context_files_skips_placeholder(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "AGENT.md").write_text("# AGENT.md\n\n*(待填写)*\n", encoding="utf-8")
    (ws / "USER.md").write_text("# USER.md\n\n- **姓名**: 张三\n- **称呼**: 三哥\n", encoding="utf-8")
    files = load_context_files(ws)
    paths = [f.path for f in files]
    assert "AGENT.md" not in paths  # 纯占位符，不进 prompt
    assert "USER.md" in paths
    assert "张三" in files[0].content


def test_load_context_files_truncates_memory(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "MEMORY.md").write_text("\n".join(f"记忆{i}" for i in range(500)), encoding="utf-8")
    files = load_context_files(ws)
    assert "更早的记忆已省略" in files[0].content
    assert "记忆499" in files[0].content
    assert "记忆0" not in files[0].content


# ---------- prompt 编译器 ----------

def _tool_schemas():
    return [{"type": "function", "function": {
        "name": "read_file", "description": "读取文件内容", "parameters": {}}}]


def test_builder_sections_gated_by_ingredients():
    # 什么原料都不给：几乎是空 prompt
    assert build_system_prompt() == ""
    # 只给工具：只有工具段
    p = build_system_prompt(tools=_tool_schemas())
    assert "工具系统" in p and "read_file" in p
    assert "工作空间文件" not in p and "运行时信息" not in p
    # 给上下文文件：文件内容编进 prompt
    p = build_system_prompt(context_files=[ContextFile(path="AGENT.md", content="我是阿牛")])
    assert "我是阿牛" in p
    # 给运行时信息
    p = build_system_prompt(runtime_info={"now": "2026-10-27 09:00:00", "model": "m1",
                                          "workspace_dir": "/tmp/ws", "cwd": "/tmp/proj",
                                          "agent_id": "default"})
    assert "2026-10-27 09:00:00" in p and "m1" in p and "/tmp/ws" in p
    # 真机教训：cwd 必须出现在工作空间段，否则 agent 以为世界只有它的家
    assert "/tmp/proj" in p and "cwd" in p


def test_builder_identity_fallback():
    # workspace 文件全空时退回配置里的性格描述；有文件时不用兜底
    p = build_system_prompt(identity_fallback="你是个简洁的助手")
    assert "你是个简洁的助手" in p
    p = build_system_prompt(context_files=[ContextFile(path="AGENT.md", content="我是阿牛")],
                            identity_fallback="你是个简洁的助手")
    assert "你是个简洁的助手" not in p


# ---------- 装配间 ----------

class _StubBot:
    """initializer 只造 Agent 不调 bot，给个占位即可。"""

    def chat(self, *a, **kw):
        raise NotImplementedError


def test_initializer_compiles_prompt_from_workspace(tmp_path):
    ws = tmp_path / "ws"
    agent = initialize_agent(bot=_StubBot(), agent_id="t1", workspace_dir=ws)
    # 模板 AGENT.md 已生成并编进 prompt
    assert (ws / "AGENT.md").exists()
    assert "工具系统" in agent.system_prompt  # 工具段
    assert "AGENT.md" in agent.system_prompt  # 上下文文件段
    assert "t1" in agent.system_prompt        # 运行时信息段


def test_recompile_after_editing_agent_md(tmp_path):
    """验收标准：改 AGENT.md → 重新装配 → 自我认知变化。"""
    ws = tmp_path / "ws"
    a1 = initialize_agent(bot=_StubBot(), workspace_dir=ws)
    assert "阿牛" not in a1.system_prompt
    (ws / "AGENT.md").write_text("# AGENT.md\n\n我的名字是阿牛。\n", encoding="utf-8")
    a2 = initialize_agent(bot=_StubBot(), workspace_dir=ws)
    assert "我的名字是阿牛" in a2.system_prompt


def test_agent_prompt_refreshes_session():
    class EchoBot:
        def chat(self, messages, tools=None, on_delta=None):
            return SimpleNamespace(content="好", tool_calls=None, usage=None)

    agent = Agent(bot=EchoBot(), system_prompt="你是阿牛")
    agent.run("你好", Context(kwargs={"session_id": "s5"}))
    session = SESSIONS.build_session("s5")
    assert session.messages[0] == {"role": "system", "content": "你是阿牛"}
    # 重新装配后 prompt 变了，历史不动、第 0 条刷新
    agent2 = Agent(bot=EchoBot(), system_prompt="你是阿牛2.0")
    agent2.run("还在吗", Context(kwargs={"session_id": "s5"}))
    assert session.messages[0]["content"] == "你是阿牛2.0"
    assert [m["role"] for m in session.messages] == ["system", "user", "assistant", "user", "assistant"]


def test_bridge_reset_agent():
    b = Bridge()
    b._agents["default"] = object()
    b.reset_agent()
    assert b._agents == {}


# ---------- 新工具 ----------

def test_edit_file_unique_replace(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("名字: *(待填写)*\n角色: 助手\n", encoding="utf-8")
    r = TOOLS.execute("edit_file", json.dumps({
        "path": str(f), "old_text": "*(待填写)*", "new_text": "阿牛"}))
    assert r.status == "success"
    assert "名字: 阿牛" in f.read_text(encoding="utf-8")


def test_edit_file_refuses_ambiguity(tmp_path):
    f = tmp_path / "b.md"
    f.write_text("x = 1\ny = 1\n", encoding="utf-8")
    r = TOOLS.execute("edit_file", json.dumps({
        "path": str(f), "old_text": "= 1", "new_text": "= 2"}))
    assert r.status == "error" and "2 次" in r.result
    r = TOOLS.execute("edit_file", json.dumps({
        "path": str(f), "old_text": "不存在", "new_text": "x"}))
    assert r.status == "error" and "没找到" in r.result
    assert f.read_text(encoding="utf-8") == "x = 1\ny = 1\n"  # 失败时文件原样


def test_current_time():
    import re
    r = TOOLS.execute("current_time", "{}")
    assert r.status == "success"
    # 回归：曾把字面量 [now.weekday()] 发给模型（f-string 大括号位置写错）
    assert "[" not in r.result and "]" not in r.result
    assert re.search(r"星期[一二三四五六日]", r.result), r.result
    names = [s["function"]["name"] for s in TOOLS.schemas()]
    assert "edit_file" in names and "current_time" in names


def test_read_file_gbk_and_dir_guard(tmp_path):
    # 回归：Windows 中文环境 GBK 文件读出来不能是乱码
    f = tmp_path / "gbk.txt"
    f.write_bytes("中文内容你好".encode("gbk"))
    r = TOOLS.execute("read_file", json.dumps({"path": str(f)}))
    assert r.status == "success" and "中文内容你好" in r.result
    # 目录传给 read_file 要给可操作的错误，而不是"文件不存在"
    r = TOOLS.execute("read_file", json.dumps({"path": str(tmp_path)}))
    assert r.status == "error" and "目录" in r.result
    # 不存在时报出解析后的绝对路径，方便模型自我纠正
    r = TOOLS.execute("read_file", json.dumps({"path": "不存在.txt"}))
    assert r.status == "error" and "已解析为" in r.result
