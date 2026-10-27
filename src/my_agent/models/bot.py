"""Bot 基类：模型层契约（阶段 4 定型版）。

阶段 4 变更（兑现 D001/D003）：bot 从 reply(query, context) 改为
chat(messages, tools, on_delta) —— 彻底的纯函数式生成器：
  进：完整的消息列表 + 工具说明书 + 流式回调
  出：BotResponse（文本 + 工具订单 + token 用量）
不碰历史、不跑循环、不管会话——那些都是上层（agent 循环）的事。
"""

from ..bridge.context import Context  # noqa: F401  保留给子类签名扩展用


class BotResponse:
    def __init__(self, content: str = "", tool_calls: list = None, usage: dict = None):
        self.content = content
        self.tool_calls = tool_calls or []  # [{"id","name","arguments"}]
        self.usage = usage


class Bot:
    def chat(self, messages: list, tools: list = None, on_delta=None) -> BotResponse:
        raise NotImplementedError
