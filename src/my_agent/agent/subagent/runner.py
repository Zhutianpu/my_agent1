"""子代理执行器：一个任务，独立上下文，一份总结回来（对齐 CowAgent subagent/runner.py）。

核心不变量（CowAgent 原话级的洞察）：
  父上下文只见到派单调用和返回的 summary。子代理路上读过的、跑过的、
  丢弃的一切都不进父上下文——这正是派单存在的意义。

SIMPLIFIED（对照 CowAgent 381 行原版）：
- 并发线程池 + 超时 + wrap-up 收尾 → 顺序执行。单用户终端场景下，
  权限闸是同步 input()，两个子代理同时抢键盘会交错成灾难。
- 工具实例浅拷贝防并发串扰 → 共享实例。顺序执行无并发，且工具无 run 级状态。
- run 记账（conversation_store）→ 无，我们没有 run 表。
- 子代理事件转播（subagent_step）→ v1 静默，结果回来后父 agent 复述。
"""

import time
import uuid

from ...common import const
from ...common.log import logger
from ..protocol.agent import Agent
from ..tools.tool_manager import TOOLS
from .templates import DEFAULT_TEMPLATE_NAME, TEMPLATES


def _build_brief(template, task: dict) -> str:
    """子代理的 system prompt：角色说明 + 任务 + 背景（对齐 _build_brief）。"""
    parts = [template.prompt, "", "你的任务：", task["goal"].strip()]
    if task.get("context", "").strip():
        parts += ["", "背景：", task["context"].strip()]
    return "\n".join(parts)


def _run_one(index: int, template, task: dict, *, bot, parent_max_turns: int) -> dict:
    """跑一个子代理任务，返回 {task_index, subagent_type, status, summary|error, duration}。"""
    started = time.time()
    result = {"task_index": index, "subagent_type": template.name}
    # 隔离三件套：独立 session（用完即弃）、无 memory（不蒸馏不落盘）、
    # 工具白名单（模板裁剪后的注册表，BLOCKED 已在模板层扣掉）。
    tool_names = template.select_tool_names(list(TOOLS._tools))
    child = Agent(
        bot=bot,  # 共享父模型（bot 是无状态生成器，共享无妨）
        system_prompt=_build_brief(template, task),
        # 预算减半 + 下限保底（CowAgent 减半原则的本土化）：
        # CowAgent 的 max_steps 基数几十起步，减半还很宽裕；我们默认才 8，
        # 照搬减半只剩 4——真机验收时 explore 查个 PLAN.md 就饿死了。
        # 6 是"ls + 读两页 + 总结"的最小体面预算。
        max_turns=max(6, parent_max_turns // 2),
        memory=None,
        tools=TOOLS.subset(tool_names),
        persist_session=False,
    )
    session_id = f"subagent_{uuid.uuid4().hex[:8]}"
    # agent_id 落成具体值：None 会顶掉 clear_session 的默认参数（踩过的坑）
    agent_id = task.get("agent_id") or const.DEFAULT_AGENT_ID
    try:
        from ...bridge.context import Context
        from ...bridge.reply import ReplyType
        reply = child.run(task["goal"], Context(kwargs={
            "session_id": session_id,
            "agent_id": agent_id,  # P2 的缝：多 agent 时传父 agent 的 id
        }))
        # Agent.run 把循环异常包成 ERROR Reply 而不是抛出（D004）——
        # 这里必须把它翻译回 failed，否则"子代理全灭"会被误报成 completed
        if reply.type == ReplyType.ERROR:
            result["status"] = "failed"
            result["error"] = reply.content
        else:
            result["status"] = "completed"
            result["summary"] = reply.content or ""
    except Exception as e:
        logger.warning(f"[SubAgent] 任务 {index}（{template.name}）失败: {e}")
        result["status"] = "failed"
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        # 弃置 session 别留在柜子里（persist_session=False 已保证不落盘，
        # 这里清内存；clear_session 的 unlink 有 missing_ok，没文件也不炸）
        from ...models.session_manager import SESSIONS
        SESSIONS.clear_session(session_id, agent_id)
    result["duration_seconds"] = round(time.time() - started, 2)
    return result


def run_tasks(tasks: list, *, bot, parent_max_turns: int) -> list:
    """顺序跑完所有任务，按下单顺序返回结果（每个任务都有始有终）。"""
    results = []
    for index, task in enumerate(tasks):
        name = task.get("subagent_type") or DEFAULT_TEMPLATE_NAME
        template = TEMPLATES.get(name) or TEMPLATES[DEFAULT_TEMPLATE_NAME]
        logger.info(f"[SubAgent] 派单 {index + 1}/{len(tasks)}: {template.name} — {task['goal'][:50]}")
        results.append(_run_one(index, template, task, bot=bot,
                                parent_max_turns=parent_max_turns))
    return results
