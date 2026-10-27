"""MCP 装配服务（对齐 CowAgent mcp/service.py 的极简版）。

读 mcp_servers.json（Claude/Cursor 的 mcpServers 格式）：

    {
      "mcpServers": {
        "time": {
          "command": "python",
          "args": ["scripts/mcp_time_server.py"],
          "risk": "read"          // 可选：只读 server 配上就不弹权限窗
        }
      }
}

每个 server：握手 → tools/list → 每个远程工具包成 McpTool 注册进 ToolManager
（ToolManager 一行不改——这就是适配器的意义）。单个 server 挂了只记日志，
不拖垮整个装配。重复调用（#reset 重装）先关掉旧进程。
"""

import json
from pathlib import Path

from ....common.log import logger
from ....config import ROOT
from .mcp_client import McpClient
from .mcp_tool import McpTool

_clients = []  # 活着的客户端，shutdown_all 用


def load_mcp_config(path=None) -> dict:
    f = Path(path) if path else ROOT / "mcp_servers.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("mcpServers", {})
    except Exception:
        logger.exception(f"[MCP] 配置读取失败: {f}")
        return {}


def start_mcp_servers(tool_manager, config_path=None) -> int:
    """启动配置里的所有 server 并注册工具。返回成功接入的工具数。"""
    shutdown_all()  # 重新装配时先杀旧进程（防 #reset 后进程泄漏）
    servers = load_mcp_config(config_path)
    count = 0
    for name, cfg in servers.items():
        if cfg.get("disabled"):
            continue
        client = McpClient(
            name=name,
            command=cfg.get("command", ""),
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
            timeout=float(cfg.get("timeout", 30)),
        )
        if not client.start():
            continue  # 日志已记，跳过这个 server
        try:
            for tool_schema in client.list_tools():
                tool_manager.register(McpTool(
                    client, tool_schema, name,
                    name_prefix=f"mcp_{name}_",
                    risk=cfg.get("risk", "write"),
                ))
                count += 1
            _clients.append(client)
            logger.info(f"[MCP] server={name} 接入 {len(client.list_tools())} 个工具")
        except Exception:
            logger.exception(f"[MCP] server={name} 拉取工具列表失败")
            client.shutdown()
    return count


def shutdown_all():
    for c in _clients:
        try:
            c.shutdown()
        except Exception:
            pass
    _clients.clear()
