"""McpTool：把单个远程 MCP 工具包装成 BaseTool（对齐 CowAgent mcp_tool.py）。

一个 MCP server 可提供多个工具，每个对应一个 McpTool 实例。
本地名加 mcp_<server>_ 前缀防撞名；调用时仍用远程原名——server 只认原名。

与内建工具的差异：内建工具注册的是类（ToolManager 实例化），
McpTool 每个实例的名字/说明书都不同（来自远程 schema），所以注册的是实例，
schema 也是实例方法（类方法拿不到实例属性）。
"""

from ....common.log import logger
from ..base_tool import BaseTool, ToolResult


class McpTool(BaseTool):
    def __init__(self, client, tool_schema: dict, server_name: str,
                 name_prefix: str = "", risk: str = "write"):
        """
        :param client: 该工具所属的 McpClient
        :param tool_schema: {"name": str, "description": str, "inputSchema": dict}
        :param risk: MCP 工具风险自报不了，由 server 配置统一指定
                     （默认 write=首次问用户；只读 server 可在 mcp_servers.json 配 "read"）
        """
        self.client = client
        self.server_name = server_name
        self._remote_name = tool_schema["name"]  # server 端只认原名
        self.name = name_prefix + self._remote_name
        self.description = tool_schema.get("description", "")
        self.params = tool_schema.get("inputSchema", {})
        self.risk = risk

    def schema(self) -> dict:  # 实例方法：遮蔽 BaseTool 的 classmethod
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params,
            },
        }

    def execute(self, **kwargs) -> ToolResult:
        logger.info(f"[McpTool] server={self.server_name} tool={self.name}")
        try:
            return ToolResult.success(self.client.call_tool(self._remote_name, kwargs))
        except Exception as e:  # D004：失败变错误文本，模型读得懂
            logger.error(f"[McpTool] {self.name} 失败: {e}")
            return ToolResult.fail(f"error: MCP 工具调用失败: {e}")
