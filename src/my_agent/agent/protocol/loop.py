"""工具循环本体（对齐 CowAgent agent_stream.py 的 run_stream 骨架）+ 循环护甲二期。

6 步：
  1. 调用方已把用户消息 append 进 session
  2. 裁剪上下文（循环外，只做一次）
  3. while turn < max_turns
  4.   bot.chat（流式，文本经 on_delta 实时出去）
  5.   无 tool_calls → 返回最终文本
  6.   有 → 记下订单 → 逐个执行回填 → 回到 3

护甲二期（2026-10-28）三件：
- 空响应重试（对齐 CowAgent agent_stream.py 1027~1076）：工具跑完模型却不说话，
  注入"催促"再问一次，用完 pop 不污染持久历史；仍空 → 兜底文案。
  SIMPLIFIED：砍了 allow_empty_response（那是给定时任务"允许沉默"用的）。
- 取消：KeyboardInterrupt 接进循环。工具订单缺口用"已中断"结果补齐——
  每个 tool_call 都必须有配对的 tool result（CowAgent cancel.py 的同款
  完整性要求），否则下一轮 API 调用直接报错。
- 模型 fallback：bot.chat 抛错且配了 fallback_model → run 内粘性切换重试一次。
  注意这不是 CowAgent 的设计（它的 fallback 是上下文窗口档位），是我们自己的护甲。
  SIMPLIFIED：只有"主→备一次"，无指数退避、无跨 run 记忆。
"""

from ...common.log import logger
from ...config import conf
from ..tools.tool_manager import TOOLS

_EXPLICIT_RESPONSE_PROMPT = "请向用户说明刚才工具执行的结果或回答用户的问题。"
_EMPTY_FALLBACK = "抱歉，我暂时无法生成回复。请尝试换一种方式描述你的需求，或稍后再试。"
_INTERRUPT_NOTE = "（⚠️ 这轮执行被 Ctrl+C 中断）"
_INTERRUPT_TOOL_RESULT = "（执行被用户中断）"


def run_loop(*, bot, session, on_event, max_turns: int, tools=None) -> str:
    # tools：阶段 11 的缝——子代理跑裁剪后的白名单注册表；None = 全局 TOOLS
    registry = tools or TOOLS
    tools_schema = registry.schemas()
    on_delta = lambda d: on_event({"type": "message_update", "data": {"delta": d}})

    def chat():
        """模型调用 + fallback：主 bot 抛错且有备用 → 粘性切换（nonlocal 换掉，
        本 run 后续 turn 都用备用的）。备用也挂：异常上去，agent.run 兜底。"""
        nonlocal bot
        try:
            return bot.chat(session.messages, tools=tools_schema or None, on_delta=on_delta)
        except KeyboardInterrupt:
            raise  # 取消不是"模型失败"，别触发 fallback
        except Exception as e:
            fallback_model = conf().get("fallback_model", "")
            if not fallback_model:
                raise
            logger.warning(f"[Loop] 主模型调用失败（{e}），切备用模型 {fallback_model}")
            on_event({"type": "notice", "data": {
                "text": f"⚠️ 主模型调用失败，本轮起切换到备用模型 {fallback_model}"}})
            from ...models.bot_factory import create_bot  # 局部 import 破环
            bot = create_bot(model=fallback_model)
            return bot.chat(session.messages, tools=tools_schema or None, on_delta=on_delta)

    def interrupted():
        """取消的统一收尾：通知 + 补一条 assistant 回复（历史保持一问一答）。"""
        on_event({"type": "notice", "data": {"text": _INTERRUPT_NOTE}})
        session.add_reply(_INTERRUPT_NOTE)
        logger.warning("[Loop] 用户中断（Ctrl+C）")
        return _INTERRUPT_NOTE

    for turn in range(1, max_turns + 1):
        on_event({"type": "turn_start", "data": {"turn": turn}})
        try:
            resp = chat()
        except KeyboardInterrupt:
            return interrupted()

        if not resp.tool_calls:
            text = resp.content or ""
            if not text and turn > 1:
                # 空响应重试：工具跑过模型却沉默 → 催促一次。
                # idx 记住注入位置，用完 pop——催促是临时工，不进持久历史。
                logger.info("[Loop] 空响应：注入催促重试一次")
                idx = len(session.messages)
                session.messages.append({"role": "user", "content": _EXPLICIT_RESPONSE_PROMPT})
                try:
                    resp = chat()
                except KeyboardInterrupt:
                    session.messages.pop(idx)
                    return interrupted()
                session.messages.pop(idx)
                text = resp.content or ""
            if not resp.tool_calls:  # 第 5 步：真收工（含首轮即空 / 重试仍空）
                if not text:
                    text = _EMPTY_FALLBACK
                    logger.warning("[Loop] 模型持续空响应，用兜底文案")
                session.add_reply(text)
                return text
            # 重试反而给了工具订单：不 break，落进下面第 6 步的工具路径

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
        was_interrupted = False
        for tc in resp.tool_calls:
            if was_interrupted:
                # 中断补齐：剩余 tool_call 也要回填结果，配对完整是硬要求
                session.messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": _INTERRUPT_TOOL_RESULT})
                continue
            on_event({"type": "tool_execution_start", "data": {
                "tool_name": tc["name"], "arguments": tc["arguments"]}})
            try:
                result = registry.execute(tc["name"], tc["arguments"])
            except KeyboardInterrupt:
                was_interrupted = True
                session.messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": _INTERRUPT_TOOL_RESULT})
                continue
            on_event({"type": "tool_execution_end", "data": {
                "tool_name": tc["name"], "status": result.status}})
            session.messages.append({
                "role": "tool", "tool_call_id": tc["id"], "content": result.result,
            })
        if was_interrupted:
            return interrupted()

    warning = f"（达到最大工具轮数 {max_turns}，强制收尾）"
    logger.warning(f"[Loop] {warning}")
    session.add_reply(warning)
    return warning
