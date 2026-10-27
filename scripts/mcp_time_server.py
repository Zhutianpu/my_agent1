"""零依赖 MCP time server（stdio，手写 JSON-RPC）。

既是 my-agent 阶段 9 的验收 server，也是测试 fixture——它证明我们的客户端
说的是协议本身，而不是靠 mcp SDK 兜底。

协议要点（与 CowAgent mcp_client.py 对齐）：
- 换行分隔 JSON；每行一个完整 JSON-RPC 消息
- initialize → 回 result；notifications/initialized 是通知（无 id），不回
- tools/list → 回工具清单；tools/call → 回 {"content": [{"type":"text","text":...}]}
- 带 id 的才回响应，id 原样带回
"""

import json
import sys
from datetime import datetime

# Windows 下管道默认 GBK，必须强制 UTF-8，否则客户端 json.loads 炸
sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

TOOLS = [
    {
        "name": "get_current_time",
        "description": "获取当前日期和时间（MCP server 版）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "echo",
        "description": "原样返回输入的文本（联调用）",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
            "required": ["text"],
        },
    },
]


def _result(req_id, result):
    sys.stdout.write(json.dumps(
        {"jsonrpc": "2.0", "id": req_id, "result": result}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        req_id = msg.get("id")  # 通知没有 id

        if method == "initialize":
            _result(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "mcp-time-server", "version": "0.1"},
            })
        elif method == "tools/list" and req_id is not None:
            _result(req_id, {"tools": TOOLS})
        elif method == "tools/call" and req_id is not None:
            params = msg.get("params", {})
            name, args = params.get("name"), params.get("arguments", {})
            if name == "get_current_time":
                text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif name == "echo":
                text = str(args.get("text", ""))
            else:
                text = f"unknown tool: {name}"
            _result(req_id, {"content": [{"type": "text", "text": text}]})
        # 通知（notifications/initialized 等）和其他方法：不回


if __name__ == "__main__":
    main()
