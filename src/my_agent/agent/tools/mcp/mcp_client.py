"""MCP stdio 客户端（对齐 CowAgent mcp_client.py，只留 stdio 传输）。

协议：JSON-RPC 2.0，换行分隔的 JSON（stdio 传输没有 Content-Length 头）。
生命周期：
  1. start()：起子进程（命令白名单 + 环境过滤），后台线程把 stdout 读进队列
     （跨平台超时读的关键：直接 readline 在 Windows 上没法超时）
  2. 握手：initialize（protocolVersion/capabilities/clientInfo）
           → 收到响应 → 发 notifications/initialized（通知无 id，不等响应）
  3. list_tools() / call_tool()：请求带自增 id，响应按 id 配对；
     通知和无 id 消息跳过；过期 id 跳过（防上次超时的残余响应错位）
  4. 一把锁串行化整条管道（stdio 只有一根管子，并发写会交错）
  5. shutdown()：杀子进程

SIMPLIFIED: CowAgent 1140 行含 SSE/HTTP 传输 + OAuth + SSRF 防护 +
分页游标 + 完整环境白名单。这里：只 stdio、不分页（本地 server 工具少）、
环境 = 当前环境去掉敏感变量 + 配置显式 env。
"""

import json
import os
import queue
import subprocess
import threading
import time

from ....common.log import logger

# stdio server 只允许这些可执行文件（PLAN 红线：命令白名单）
_COMMAND_ALLOWLIST = {"python", "python.exe", "node", "npx", "uvx", "uv"}

# 不透传给子进程的环境变量特征（API key 不该漏进 MCP server）
_SENSITIVE_ENV_MARKERS = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")

_PROTOCOL_VERSION = "2024-11-05"


class McpToolCallError(RuntimeError):
    """一次 MCP 工具调用失败（对齐 CowAgent）。"""


class McpClient:
    def __init__(self, name: str, command: str, args: list = None,
                 env: dict = None, timeout: float = 30):
        self.name = name
        self.command = command
        self.args = args or []
        self.extra_env = env or {}
        self.timeout = timeout
        self._proc = None
        self._read_queue = queue.Queue()
        self._lock = threading.Lock()  # 串行化管道上的所有请求
        self._next_id = 1
        self._initialized = False

    # ---- 生命周期 ----

    def start(self) -> bool:
        """起进程 + 握手。失败清理干净返回 False（装配间跳过这个 server）。"""
        base = os.path.basename(self.command).lower()
        if base not in _COMMAND_ALLOWLIST:
            logger.warning(f"[MCP:{self.name}] 命令不在白名单: {self.command}"
                           f"（只允许 {sorted(_COMMAND_ALLOWLIST)}）")
            return False
        env = {k: v for k, v in os.environ.items()
               if not any(m in k.upper() for m in _SENSITIVE_ENV_MARKERS)}
        env.update({str(k): str(v) for k, v in self.extra_env.items()})
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", env=env, bufsize=1,
            )
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] 启动失败: {e}")
            return False
        threading.Thread(target=self._drain_stdout, daemon=True).start()

        try:
            resp = self._request("initialize", {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "my-agent", "version": "0.1"},
            })
            if "error" in resp:
                raise McpToolCallError(f"握手被拒: {resp['error']}")
            self._notify("notifications/initialized", {})
            self._initialized = True
            logger.info(f"[MCP:{self.name}] 握手完成（pid={self._proc.pid}）")
            return True
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] 握手失败: {e}")
            self.shutdown()
            return False

    def shutdown(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
        self._proc = None
        self._initialized = False

    # ---- 协议方法 ----

    def list_tools(self) -> list:
        resp = self._request("tools/list", {})
        return (resp.get("result") or {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        """返回成功文本；失败抛 McpToolCallError（适配器会转成错误文本）。"""
        resp = self._request("tools/call", {"name": name, "arguments": arguments})
        result = resp.get("result") or {}
        content = result.get("content", [])
        parts = [item.get("text", "") for item in content if item.get("type") == "text"]
        text = "\n".join(parts)
        if not parts and "structuredContent" in result:
            text = json.dumps(result["structuredContent"], ensure_ascii=False)
        if result.get("isError"):
            raise McpToolCallError(text or "MCP 工具执行失败")
        return text

    # ---- stdio 传输 internals ----

    def _drain_stdout(self):
        """后台线程：逐行读进队列（队列 get 才有跨平台超时）。"""
        try:
            for line in self._proc.stdout:
                self._read_queue.put(line)
        except Exception:
            pass
        finally:
            self._read_queue.put("")  # EOF 哨兵

    def _notify(self, method: str, params: dict):
        """通知：无 id，不等响应。"""
        self._proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params,
        }) + "\n")
        self._proc.stdin.flush()

    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            self._proc.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": req_id, "method": method, "params": params,
            }) + "\n")
            self._proc.stdin.flush()

            # 一个总死线：跳过的行（通知/过期 id）不重置超时
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"[MCP:{self.name}] {method} 响应超时（{self.timeout}s）")
                line = self._read_queue.get(timeout=remaining).strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" not in data:
                    continue  # 通知，跳过
                if data["id"] != req_id:
                    logger.warning(f"[MCP:{self.name}] 过期响应 id={data['id']}，跳过")
                    continue
                if "error" in data:
                    raise McpToolCallError(f"{method} RPC 错误: {data['error']}")
                return data
