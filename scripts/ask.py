"""阶段 1 验收脚本：真机问一句，看回复。

用法（先在项目根配好 config.json 或 .env）：
    python scripts/ask.py "你好，介绍一下你自己"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from my_agent.bridge.context import Context, ContextType
from my_agent.models.bot_factory import create_bot


def main():
    query = " ".join(sys.argv[1:]) or "你好"
    bot = create_bot()
    ctx = Context(ContextType.TEXT, query, kwargs={"session_id": "cli-demo"})
    reply = bot.reply(query, ctx)
    print(f"[{reply.type}] {reply.content}")


if __name__ == "__main__":
    main()
