"""阶段 9 验收测试：MCP（stdio 客户端 + 适配器 + 装配服务）。

两层测法：
- 适配器层用假 client（不起进程，快）
- 客户端层起真子进程跑 scripts/mcp_time_server.py（零依赖手写 server，
  证明我们说的是协议本身而不是靠 SDK）
"""

import json
import sys

from my_agent.agent.tools import TOOLS
from my_agent.agent.tools.mcp import McpClient, McpTool, shutdown_all, start_mcp_servers
from my_agent.agent.tools.mcp.service import load_mcp_config
from my_agent.config import ROOT

SERVER_SCRIPT = ROOT / "scripts" / "mcp_time_server.py"


def teardown_function():
    shutdown_all()


# ---------- 适配器（假 client，不起进程） ----------

class FakeClient:
    def __init__(self, result="远程结果", boom=False):
        self.result = result
        self.boom = boom
        self.calls = []

    def call_tool(self, name, params):
        self.calls.append((name, params))
        if self.boom:
            raise RuntimeError("server 挂了")
        return self.result


def _make_tool(client=None, **kw):
    schema = {"name": "get_current_time", "description": "远程时间",
              "inputSchema": {"type": "object", "properties": {}}}
    return McpTool(client or FakeClient(), schema, server_name="time",
                   name_prefix="mcp_time_", **kw)


def test_mcp_tool_adapter():
    client = FakeClient()
    tool = _make_tool(client)
    assert tool.name == "mcp_time_get_current_time"      # 本地名带前缀
    assert tool.description == "远程时间"
    s = tool.schema()
    assert s["function"]["name"] == "mcp_time_get_current_time"  # 说明书能编译
    r = tool.execute()
    assert r.status == "success" and r.result == "远程结果"
    assert client.calls[0][0] == "get_current_time"      # 远程调用用原名（无前缀）


def test_mcp_tool_failure_becomes_error_text():
    r = _make_tool(FakeClient(boom=True)).execute()
    assert r.status == "error" and "server 挂了" in r.result  # D004 一致性


def test_tool_manager_registers_instances():
    """契约升级：register 既收类（内建）也收实例（MCP）。"""
    tool = _make_tool()
    TOOLS.register(tool)
    assert TOOLS.get("mcp_time_get_current_time") is tool
    r = TOOLS.execute("mcp_time_get_current_time", "{}")
    assert r.status == "success"


# ---------- 客户端（真子进程，协议级联调） ----------

def _start_real_client():
    client = McpClient("time", sys.executable, [str(SERVER_SCRIPT)], timeout=15)
    assert client.start(), "握手失败"
    return client


def test_handshake_list_call_over_stdio():
    client = _start_real_client()
    try:
        tools = client.list_tools()
        names = [t["name"] for t in tools]
        assert "get_current_time" in names and "echo" in names
        out = client.call_tool("echo", {"text": "协议通了"})
        assert out == "协议通了"
        out = client.call_tool("get_current_time", {})
        assert len(out) == 19  # YYYY-MM-DD HH:MM:SS
    finally:
        client.shutdown()
    assert client._proc is None or client._proc.poll() is not None  # 进程真杀了


def test_command_allowlist():
    client = McpClient("evil", "rm", ["-rf", "/"])
    assert not client.start()  # 白名单外直接拒
    assert client._proc is None


# ---------- 装配服务 ----------

def test_service_registers_prefixed_tools(tmp_path):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "time": {"command": sys.executable, "args": [str(SERVER_SCRIPT)], "risk": "read"},
        "bad": {"command": "rm", "args": []},  # 白名单外的：挂它的，别拖累别人
    }}), encoding="utf-8")
    count = start_mcp_servers(TOOLS, config_path=cfg)
    assert count == 2  # time server 的两个工具
    assert TOOLS.get("mcp_time_echo") is not None
    assert TOOLS.get("mcp_bad_echo") is None
    assert TOOLS.get("mcp_time_echo").risk == "read"  # server 级风险配置生效
    r = TOOLS.execute("mcp_time_echo", json.dumps({"text": "端到端"}))
    assert "端到端" in r.result


def test_load_config_missing_and_bad(tmp_path):
    assert load_mcp_config(tmp_path / "没有.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{坏", encoding="utf-8")
    assert load_mcp_config(bad) == {}
