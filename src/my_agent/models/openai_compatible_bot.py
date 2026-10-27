"""OpenAI 兼容 bot（阶段 4 版）：单次、流式、纯生成。

chat() = 一次 API 调用：流式读回文本（on_delta 逐段回调，终端逐字显示），
同时累积工具订单碎片（流式里 tool_calls 是分块到达的，按 index 拼起来）。
循环、历史、会话全部上移到 agent 层——这个文件只认识"一次调用"。
"""

from openai import OpenAI

from ..common.log import logger
from ..config import conf
from .bot import Bot, BotResponse


class OpenAICompatibleBot(Bot):
    def __init__(self):
        self.model = conf().get("model")
        self.client = OpenAI(
            api_key=conf().get("open_ai_api_key"),
            base_url=conf().get("open_ai_api_base"),
        )

    def chat(self, messages: list, tools: list = None, on_delta=None) -> BotResponse:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        content_parts = []
        tc_acc = {}  # index -> {"id","name","arguments":[碎片]}
        usage = None

        for chunk in self.client.chat.completions.create(**kwargs):
            if getattr(chunk, "usage", None):
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                }
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                if on_delta:
                    on_delta(delta.content)
            for tc in (delta.tool_calls or []):
                acc = tc_acc.setdefault(tc.index, {"id": None, "name": None, "arguments": []})
                if tc.id:
                    acc["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        acc["name"] = tc.function.name
                    if tc.function.arguments:
                        acc["arguments"].append(tc.function.arguments)

        tool_calls = [
            {"id": a["id"], "name": a["name"], "arguments": "".join(a["arguments"])}
            for _, a in sorted(tc_acc.items())
        ]
        if usage:
            logger.info(
                f"[Bot] model={self.model} tokens={usage['prompt_tokens']}+{usage['completion_tokens']}"
            )
        return BotResponse("".join(content_parts), tool_calls, usage)
