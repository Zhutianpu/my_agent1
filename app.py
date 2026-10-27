"""my-agent 入口：起 terminal channel。

对齐 CowAgent 的 app.py：加载配置 → 起 channel。SIMPLIFIED 到只有一路 channel。
"""

from my_agent.channel.terminal import TerminalChannel

if __name__ == "__main__":
    TerminalChannel().startup()
