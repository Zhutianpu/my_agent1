"""subagent 派发工具：主 agent 把自包含的任务交给子代理（阶段 11）。

对齐 CowAgent tools/subagent/subagent.py。它是"这个 agent 完成工作的方式"，
不是"联系平级 agent 的方式"——跨 agent 边界的派单是 P2 的活。

权限设计：本工具 risk=read——派单动作本身不改任何东西；子代理跑起来后
用的每个工具照常过权限闸（ToolManager 级，白名单子集自动继承），
所以"派单"不会变成绕过权限的后门（CowAgent 同款原则）。

SIMPLIFIED：
- 无 SubagentSettings 配置——永远启用，顺序执行，任务数硬上限 3
- 结果只回 JSON（CowAgent 还拼 markdown 给人看，我们的 channel 已有工具事件行）
"""

import json

from ...common.log import logger
from ..subagent.templates import TEMPLATES
from .base_tool import BaseTool, ToolResult

_MAX_TASKS = 3

_TYPE_LISTING = "\n".join(f"- {n}: {t.description}" for n, t in sorted(TEMPLATES.items()))


class SubagentTool(BaseTool):
    name = "subagent"
    risk = "read"
    description = (
        "把一个自包含的任务派给子代理：它在自己的独立上下文里干活，只把结论带回来，"
        "它读过的文件、跑过的命令都不占用你的上下文。\n\n"
        f"适合较重的调查/搜索/资料收集（单任务用 goal，多任务用 tasks，最多 {_MAX_TASKS} 个）。"
        "子代理比自己做更慢更贵，小事自己做，别派。\n\n"
        "子代理看不到这场对话也没法中途问你，所以 goal 要写完整，"
        "把需要的文件路径、结论、约束都放进 context；交代得含糊，带回来的也含糊。"
        "它的汇报不会直接给用户看——读完后用你自己的话转述重点。\n\n"
        f"可用的子代理类型：\n{_TYPE_LISTING}"
    )
    params = {
        "type": "object",
        "properties": {
            "goal": {"type": "string",
                     "description": "要子代理完成的事。写成给素未谋面的人的完整指令。"},
            "context": {"type": "string",
                        "description": "子代理需要但查不到的一切：路径、报错、已定的决策。你省略的它就永远不知道。"},
            "subagent_type": {"type": "string",
                              "description": "用哪种子代理（见工具描述清单），缺省 general-purpose。"},
            "tasks": {
                "type": "array",
                "description": "一次派多个任务（字段同 goal/context/subagent_type），顺序执行",
                "items": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "context": {"type": "string"},
                        "subagent_type": {"type": "string"},
                    },
                    "required": ["goal"],
                },
            },
        },
        "required": [],
    }

    # ---- 执行 ----

    @staticmethod
    def _collect_tasks(goal, context, subagent_type, tasks) -> list:
        """单任务/多任务两种下单形态统一成任务列表（对齐 _collect_tasks）。"""
        out = []
        if isinstance(tasks, list):
            for entry in tasks:
                if not isinstance(entry, dict):
                    continue
                g = str(entry.get("goal") or "").strip()
                if g:
                    out.append({"goal": g,
                                "context": str(entry.get("context") or ""),
                                "subagent_type": str(entry.get("subagent_type") or "").strip() or None})
        if not out and str(goal or "").strip():
            out.append({"goal": str(goal).strip(),
                        "context": str(context or ""),
                        "subagent_type": str(subagent_type or "").strip() or None})
        return out

    def execute(self, goal="", context="", subagent_type=None, tasks=None) -> ToolResult:
        tasks_list = self._collect_tasks(goal, context, subagent_type, tasks)
        if not tasks_list:
            return ToolResult.fail("error: 需要 goal，或 tasks 里至少一条带 goal 的任务")
        if len(tasks_list) > _MAX_TASKS:
            return ToolResult.fail(f"error: 一次最多派 {_MAX_TASKS} 个任务，拆分多轮派")
        unknown = sorted({t["subagent_type"] for t in tasks_list
                          if t["subagent_type"] and t["subagent_type"] not in TEMPLATES})
        if unknown:
            return ToolResult.fail(
                f"error: 未知的子代理类型: {', '.join(unknown)}（可用的: {', '.join(sorted(TEMPLATES))}）")

        # 子代理共享父模型：bot 从 Bridge 拿（与父 agent 同一个缓存实例）
        from ...bridge.bridge import Bridge  # 局部 import 破环
        from ...config import conf
        from ..subagent.runner import run_tasks

        logger.info(f"[SubagentTool] 派单 {len(tasks_list)} 个任务")
        results = run_tasks(
            tasks_list, bot=Bridge().get_bot("chat"),
            parent_max_turns=int(conf().get("agent_max_turns", 16)),
        )
        payload = json.dumps({"results": results}, ensure_ascii=False)
        if all(r["status"] != "completed" for r in results):
            # 全灭还报 success，父 agent 会拿不存在的结论去汇报（CowAgent 同款防御）
            return ToolResult.fail(payload)
        return ToolResult.success(payload)
