"""my-agent 入口：起 terminal channel。

对齐 CowAgent 的 app.py：加载配置 → 起 channel。SIMPLIFIED 到只有一路 channel。
阶段 9：退出时关掉 MCP 子进程（不留孤儿）。
"""

from my_agent.channel.terminal import TerminalChannel

if __name__ == "__main__":
    try:
        TerminalChannel().startup()
    finally:
        from my_agent.agent.tools.mcp import shutdown_all
        shutdown_all()
