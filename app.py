"""my-agent 入口：channel_factory 按配置起 channel（对齐 CowAgent app.py）。

阶段 10：channel 从配置读（"channel": "terminal" | "web"），默认 terminal。
退出时关掉 MCP 子进程（不留孤儿）。
"""

from my_agent.channel.factory import create_channel

if __name__ == "__main__":
    try:
        create_channel().startup()
    finally:
        from my_agent.agent.tools.mcp import shutdown_all
        shutdown_all()
