"""MCP（Model Context Protocol）支持（对齐 CowAgent agent/tools/mcp 的 stdio 简化版）。

  mcp_client.py —— JSON-RPC 2.0 over stdio 客户端（换行分隔 JSON，子进程管道）
  mcp_tool.py    —— 适配器：远程工具包成 BaseTool，模型分不清本地/远程
  service.py     —— 读 mcp_servers.json → 握手 → 注册进 ToolManager

SIMPLIFIED: 只做 stdio 传输（CowAgent 还有 SSE/HTTP/OAuth/tool_retrieval 动态加载）。
"""

from .mcp_client import McpClient, McpToolCallError
from .mcp_tool import McpTool
from .service import shutdown_all, start_mcp_servers

__all__ = ["McpClient", "McpToolCallError", "McpTool", "start_mcp_servers", "shutdown_all"]
