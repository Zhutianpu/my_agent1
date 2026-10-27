"""阶段 1 验收测试（阶段 4 契约修订版）：bot 是纯生成器 chat(messages)->BotResponse。

FakeClient 剧本：openai SDK 的流式返回是一串 chunk，用 SimpleNamespace 拼假 chunk。
"""

from types import SimpleNamespace

from my_agent.bridge.context import Context, ContextType
from my_agent.models.bot import Bot, BotResponse
from my_agent.models.bot_factory import create_bot, _BOT_TABLE
from my_agent.models.openai_compatible_bot import OpenAICompatibleBot
from my_agent.common import const


def _chunk(content=None):
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


class FakeCompletions:
    def __init__(self, chunks):
        self.chunks = chunks

    def create(self, **kwargs):
        return iter(self.chunks)


class FakeClient:
    def __init__(self, chunks):
        self.chat = SimpleNamespace(completions=FakeCompletions(chunks))


def test_bot_chat_streams_content():
    """契约：messages 进来，BotResponse 出去；流式碎片拼成完整文本并经 on_delta 逐段回调。"""
    bot = OpenAICompatibleBot()
    bot.client = FakeClient([_chunk("你"), _chunk("好"), _chunk("！")])
    deltas = []
    resp = bot.chat([{"role": "user", "content": "hi"}], on_delta=deltas.append)
    assert isinstance(resp, BotResponse)
    assert resp.content == "你好！"
    assert deltas == ["你", "好", "！"]
    assert resp.tool_calls == []


def test_bot_is_pure_generator():
    """纯生成器证据：连续两次 chat 互不牵连（bot 自己不存历史）。"""
    bot = OpenAICompatibleBot()
    bot.client = FakeClient([_chunk("A")])
    bot.chat([{"role": "user", "content": "1"}])
    bot.client = FakeClient([_chunk("B")])
    resp = bot.chat([{"role": "user", "content": "2"}])
    assert resp.content == "B"  # 第二次调用里没有任何第一次的痕迹


def test_context_kwargs_pocket():
    """口袋：元数据塞进去、原样取出来，Context 类本身不用改。"""
    ctx = Context(ContextType.TEXT, "内容")
    ctx["session_id"] = "abc"
    ctx["on_event"] = lambda e: None
    assert ctx["session_id"] == "abc"
    assert "on_event" in ctx
    assert ctx.get("不存在的键") is None


def test_factory_rejects_unknown():
    try:
        create_bot("不存在的厂商")
        assert False, "应该抛 ValueError"
    except ValueError as e:
        assert "未知 bot_type" in str(e)


def test_factory_registered():
    assert const.OPENAI_COMPATIBLE in _BOT_TABLE
