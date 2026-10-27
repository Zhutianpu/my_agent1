"""阶段 7 验收测试：记忆三条线——持久化（7a）、蒸馏（7b）、检索（7c）。

全离线：蒸馏/做梦用的是剧本机器人（ScriptedBot），检索是纯关键词。
"""

import json
import shutil
from datetime import datetime
from types import SimpleNamespace

from my_agent.agent.memory import MemoryManager, MemoryStore
from my_agent.agent.memory.store import chunk_text
from my_agent.agent.prompt import build_system_prompt
from my_agent.agent.protocol.agent import Agent
from my_agent.agent.tools import TOOLS
from my_agent.agent.tools.memory_search import MemorySearchTool
from my_agent.bridge.context import Context
from my_agent.config import ROOT
from my_agent.models.session_manager import SESSIONS


class ScriptedBot:
    """按剧本依次吐 content 的假 bot（蒸馏/做梦/对话都用它）。"""

    def __init__(self, script):
        self.script = iter(script)
        self.seen = []

    def chat(self, messages, tools=None, on_delta=None):
        self.seen.append(list(messages))
        return SimpleNamespace(content=next(self.script), tool_calls=None, usage=None)


# ---------- 7a 持久化 ----------

def test_session_persistence_roundtrip():
    SESSIONS.persist = True
    agent_id = "test7_persist"
    try:
        agent = Agent(bot=ScriptedBot(["第一次回答"]))
        agent.run("第一句话", Context(kwargs={"session_id": "s", "agent_id": agent_id}))
        # 模拟重启：清空内存柜子，文件还在
        SESSIONS.sessions.clear()
        session = SESSIONS.build_session("s", agent_id)
        roles = [m["role"] for m in session.messages]
        assert roles == ["system", "user", "assistant"]
        assert session.messages[1]["content"] == "第一句话"
    finally:
        shutil.rmtree(ROOT / "workspaces" / agent_id, ignore_errors=True)


def test_clear_session_deletes_file():
    SESSIONS.persist = True
    agent_id = "test7_clear"
    try:
        agent = Agent(bot=ScriptedBot(["答"]))
        agent.run("问", Context(kwargs={"session_id": "s", "agent_id": agent_id}))
        f = ROOT / "workspaces" / agent_id / "sessions" / "s.jsonl"
        assert f.exists()
        SESSIONS.clear_session("s", agent_id)
        assert not f.exists()
    finally:
        shutil.rmtree(ROOT / "workspaces" / agent_id, ignore_errors=True)


# ---------- 7b 蒸馏 ----------

def test_flush_writes_daily_diary(tmp_path):
    bot = ScriptedBot(["- 用户喜欢简洁回复\n- 决定：项目用中文文档"])
    mem = MemoryManager(tmp_path, bot)
    discarded = [
        {"role": "user", "content": "我喜欢简洁的回复"},
        {"role": "assistant", "content": "记住了"},
    ]
    assert mem.flush(discarded)
    diary = mem.today_file().read_text(encoding="utf-8")
    assert "用户喜欢简洁回复" in diary
    assert datetime.now().strftime("%Y-%m-%d") in mem.today_file().name


def test_flush_empty_or_chitchat_skipped(tmp_path):
    assert not MemoryManager(tmp_path, ScriptedBot([])).flush([])  # 空批次不调 LLM
    bot = ScriptedBot(["无"])
    assert not MemoryManager(tmp_path, bot).flush([{"role": "user", "content": "嗯"}])
    assert not list((tmp_path / "memory").glob("*.md"))  # "无"不落盘


def test_dream_consolidates_into_main_memory(tmp_path):
    (tmp_path / "memory").mkdir()
    today = datetime.now().strftime("%Y-%m-%d")
    (tmp_path / "memory" / f"{today}.md").write_text("# 日记\n- 用户叫张三\n", encoding="utf-8")
    bot = ScriptedBot(["# MEMORY.md - 长期记忆\n\n- 用户叫张三（称呼三哥）\n"])
    mem = MemoryManager(tmp_path, bot)
    msg = mem.dream()
    assert "蒸馏" in msg
    assert "张三" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_dream_without_dailies_noop(tmp_path):
    mem = MemoryManager(tmp_path, ScriptedBot(["不该被用到"]))
    assert "没有日记" in mem.dream()


def test_trim_triggers_flush_via_agent(tmp_path, monkeypatch):
    """集成：裁剪即蒸馏——预算外消息在**循环前**蒸馏，摘要注回活上下文。

    时序（真机抓过的坑）：蒸馏必须在循环前——否则"刚写完的东西被裁掉，
    用户下一句回复时模型当场失忆"。预算=4 时第三轮触发首次裁剪。"""
    monkeypatch.setenv("CONVERSATION_MAX_MESSAGES", "4")
    bot = ScriptedBot(["回答1", "回答2", "- 蒸馏出的要点", "回答3"])
    agent = Agent(bot=bot, memory=MemoryManager(tmp_path, bot))
    ctx = lambda: Context(kwargs={"session_id": "trim7"})
    agent.run("问题1", ctx())
    agent.run("问题2", ctx())
    assert not list((tmp_path / "memory").glob("*.md"))  # 还没超预算
    agent.run("问题3", ctx())  # 超预算：先蒸馏（第3次LLM调用），再循环（第4次）
    diaries = list((tmp_path / "memory").glob("*.md"))
    assert len(diaries) == 1 and "蒸馏出的要点" in diaries[0].read_text(encoding="utf-8")
    flush_call, loop_call = bot.seen[2], bot.seen[3]
    assert "问题1" in str(flush_call)            # 蒸馏输入是被裁掉的对话
    assert "早前对话的蒸馏摘要" in str(loop_call)  # 摘要注回了活上下文
    assert "蒸馏出的要点" in str(loop_call)


def test_summary_note_survives_trim():
    """摘要注回消息是头部 system 群的一员，后续裁剪不许把它裁掉。"""
    session = SESSIONS.build_session("sum7")
    session.inject_summary("第一批要点")
    for i in range(10):
        session.add_query(f"q{i}")
        session.add_reply(f"a{i}")
    import os
    os.environ["CONVERSATION_MAX_MESSAGES"] = "6"
    try:
        session.discard_exceeding()
    finally:
        del os.environ["CONVERSATION_MAX_MESSAGES"]
    assert session.messages[0]["role"] == "system"
    assert "第一批要点" in session.messages[1]["content"]
    # 再次注回是替换不是堆积
    session.inject_summary("第二批要点")
    assert "第二批要点" in session.messages[1]["content"]
    assert sum(1 for m in session.messages if "蒸馏摘要" in str(m.get("content", ""))) == 1
    # 裁剪后开头必须是 user（无孤儿 tool/assistant）
    assert session.messages[2]["role"] == "user"


# ---------- 7c 检索 ----------

def test_chunker_overlap():
    text = "\n".join(f"第{i}行" + "x" * 100 for i in range(50))  # 每行 100+ 字符
    chunks = chunk_text(text, "t.md")
    assert len(chunks) > 1
    # 相邻块有重叠行（防答案断在边界）
    assert chunks[1].start_line < chunks[0].end_line


def test_store_keyword_search(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "MEMORY.md").write_text("# 长期记忆\n用户喜欢喝茶\n", encoding="utf-8")
    (tmp_path / "memory" / "2026-10-26.md").write_text(
        "# 日记\n讨论了 CowAgent 架构\n用户喜欢喝茶胜过咖啡\n", encoding="utf-8")
    store = MemoryStore(tmp_path)
    hits = store.search("喝茶")
    assert hits and "喝茶" in hits[0].text
    assert not store.search("不存在的词")
    assert store.search("") == []


def test_memory_search_tool(tmp_path):
    (tmp_path / "MEMORY.md").write_text("用户的猫叫年糕", encoding="utf-8")
    MemorySearchTool.bind(MemoryStore(tmp_path))
    r = TOOLS.execute("memory_search", json.dumps({"query": "猫"}))
    assert r.status == "success" and "年糕" in r.result
    r = TOOLS.execute("memory_search", json.dumps({"query": "恐龙"}))
    assert "没有" in r.result


def test_builder_memory_section_gated():
    assert "最近记忆" not in build_system_prompt()
    p = build_system_prompt(memory_digest="- 用户喜欢喝茶")
    assert "最近记忆" in p and "用户喜欢喝茶" in p and "memory_search" in p
