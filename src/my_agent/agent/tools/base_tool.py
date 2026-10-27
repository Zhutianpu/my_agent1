"""工具基类：模型与 harness 之间的"合同模板"。

契约（对齐 CowAgent base_tool.py）：
  name / description / params —— 说明书三要素，编译进 API 的 tools 参数给模型看
  execute(**kwargs) -> ToolResult —— 模型下单后，harness 真的执行

ToolResult 分离两种读者：result 给模型读（写进 messages），status 给 harness
判断成败（事件图标 ✓/✗）。SIMPLIFIED: 砍掉了 CowAgent 的 display（人类可读版）、
parallel_safe、stage 等，需要时再加。
"""


class ToolResult:
    def __init__(self, status: str, result: str):
        self.status = status  # "success" | "error"
        self.result = result

    @staticmethod
    def success(result: str):
        return ToolResult("success", result)

    @staticmethod
    def fail(result: str):
        return ToolResult("error", result)


class BaseTool:
    name: str = "base_tool"
    description: str = ""
    params: dict = {}  # JSON Schema

    def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError

    @classmethod
    def schema(cls) -> dict:
        """编译成 OpenAI tools 参数格式——模型的说明书。"""
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": cls.params,
            },
        }
