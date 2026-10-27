"""工具循环本体（对齐 CowAgent agent_stream.py 的 run_stream 骨架）。

6 步：
  1. 调用方已把用户消息 append 进 session
  2. 裁剪上下文（循环外，只做一次）
  3. while turn < max_turns
  4.   bot.chat（流式，文本经 on_delta 实时出去）
  5.   无 tool_calls → 返回最终文本
  6.   有 → 记下订单 → 逐个执行回填 → 回到 3
"""

from ...common.log import logger
from ..tools.tool_manager import TOOLS


def run_loop(*, bot, session, on_event, max_turns: int) -> str:
    tools_schema = TOOLS.schemas()

    for turn in range(1, max_turns + 1):
        on_event({"type": "turn_start", "data": {"turn": turn}})
        resp = bot.chat(
            session.messages,
            tools=tools_schema or None,
            on_delta=lambda d: on_event({"type": "message_update", "data": {"delta": d}}),
        )

        if not resp.tool_calls:  # 第 5 步：收工
            text = resp.content or "（模型返回了空响应）"
            session.add_reply(text)
            return text

        # 第 6 步：先记订单（assistant 带 tool_calls），再逐个执行回填（role=tool）
        session.messages.append({
            "role": "assistant",
            "content": resp.content or "",
            "tool_calls": [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in resp.tool_calls
            ],
        })
        for tc in resp.tool_calls:
            on_event({"type": "tool_execution_start", "data": {
                "tool_name": tc["name"], "arguments": tc["arguments"]}})
            result = TOOLS.execute(tc["name"], tc["arguments"])
            on_event({"type": "tool_execution_end", "data": {
                "tool_name": tc["name"], "status": result.status}})
            session.messages.append({
                "role": "tool", "tool_call_id": tc["id"], "content": result.result,
            })

    warning = f"（达到最大工具轮数 {max_turns}，强制收尾）"
    logger.warning(f"[Loop] {warning}")
    session.add_reply(warning)
    return warning
