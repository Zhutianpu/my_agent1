"""工具注册表：说明书编译 + 执行台。

两份视图在这里汇合：
  schemas()  —— 给模型的视图：所有工具的说明书编成 API tools 参数
  execute()  —— 给代码的视图：按 name 查字典执行，所有失败统一变成
               错误文本回给模型（模型能读懂错误并自我修正，异常不行）

契约铁律：加新工具 = 写个子类 + register 一行，别处不动。
"""

import json

from ...common.log import logger
from .base_tool import BaseTool, ToolResult


class ToolManager:
    def __init__(self):
        self._tools = {}

    def register(self, tool):
        """登记工具。内建工具传类（这里实例化）；MCP 工具传实例
        （每个实例的名字/说明书来自远程 schema，不能走类）。"""
        if isinstance(tool, type):
            assert issubclass(tool, BaseTool)
            tool = tool()
        self._tools[tool.name] = tool

    def get(self, name):
        return self._tools.get(name)

    def subset(self, names) -> "ToolManager":
        """裁剪出只含 names 的新注册表，工具实例共享（阶段 11 子代理白名单）。

        P2 的缝兑现：多 agent/角色按白名单各拿各的工具集。execute 里的
        权限闸是 ToolManager 级别的，子集自动继承——派单不能绕过权限。
        """
        sub = ToolManager()
        sub._tools = {n: t for n, t in self._tools.items() if n in set(names)}
        return sub

    def schemas(self) -> list:
        return [t.schema() for t in self._tools.values()]

    def execute(self, name: str, arguments_json: str) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.fail(f"error: 未知工具 '{name}'（可用的只有: {list(self._tools)}）")
        try:
            kwargs = json.loads(arguments_json or "{}")
        except json.JSONDecodeError as e:
            return ToolResult.fail(f"error: 参数不是合法 JSON: {e}")
        # 权限闸（阶段 6）：危险操作先过闸。拒绝变成错误文本回给模型（D004 延伸）。
        from ..permission import GATE  # 局部 import：permission 不认识 tools，防环
        decision = GATE.check(tool, kwargs)
        if not decision:
            return ToolResult.fail(f"error: 权限拒绝：{decision.reason}")
        try:
            return tool.execute(**kwargs)
        except TypeError as e:
            return ToolResult.fail(f"error: 参数不对: {e}（合同要求: {tool.params.get('properties', {}).keys()}）")
        except Exception as e:
            logger.exception(f"[Tools] {name} 执行异常")
            return ToolResult.fail(f"error: {type(e).__name__}: {e}")


TOOLS = ToolManager()
