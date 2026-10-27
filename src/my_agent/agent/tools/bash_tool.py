"""run_command：执行 shell 命令。

防护（对齐 CowAgent bash 工具的思路，简化版）：
  1. 危险命令黑名单——宁可误杀不可放过
  2. 超时强制终止
  3. 输出截断（理由同 read_file）
"""

import re
import subprocess

from ...config import conf
from .base_tool import BaseTool, ToolResult

# 危险模式：命中即拒。SIMPLIFIED: CowAgent 有分级的确认机制，这里只做硬黑名单。
_DANGEROUS = [
    r"rm\s+-rf\s+[/\\]",
    r"del\s+/[fs].*[/\\][a-z]:",   # del /f /s c:\...
    r"\bformat\b\s+[a-z]:",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r":\(\)\s*\{",                  # fork 炸弹
]


class RunCommandTool(BaseTool):
    name = "run_command"
    risk = "write"  # 任意命令执行，首次问用户（硬黑名单仍是最后一道防线）
    description = "执行一条 shell 命令并返回输出（有超时和危险命令拦截）。"
    params = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "integer", "description": "超时秒数（默认 60）", "default": 60},
        },
        "required": ["command"],
    }

    def execute(self, command: str, timeout: int = 60) -> ToolResult:
        for pat in _DANGEROUS:
            if re.search(pat, command, re.IGNORECASE):
                return ToolResult.fail(f"error: 危险命令已拦截: {command}")
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=min(timeout, 300), encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return ToolResult.fail(f"error: 命令超时（{timeout}s）已终止")
        out = (proc.stdout or "") + (proc.stderr or "")
        max_chars = conf().get("tool_result_max_chars", 6000)
        if len(out) > max_chars:
            out = out[:max_chars] + "\n...（输出已截断）"
        status = "success" if proc.returncode == 0 else "error"
        text = f"[exit {proc.returncode}]\n{out.strip() or '(无输出)'}"
        return ToolResult(status, text)
