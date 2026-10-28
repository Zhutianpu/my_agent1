"""信箱：agent 之间的异步留言（对齐 CowAgent multiagent/transport.py 的极简版）。

CowAgent 的 transport 是跨进程信箱（InvokeRequest 带 trace/depth/mode，
走 socket 投递给另一个 agent 进程）。我们单进程单机，信箱退化成
每个 agent 工作目录下的一个 jsonl 文件：

  workspaces/<agent_id>/mailbox.jsonl   一行一条留言

- send()  追加一行（写不进对方上下文——对方还没在跑）
- drain() 对方下次跑起来时读走并清空——"留言要等对方上线才签收"

SIMPLIFIED：无 socket、无 trace/depth（循环委托靠工具白名单结构级挡住，
见 agent_delegate.py）、无 mode 三态（DELEGATE 就是派单工具，SPEAK 就是留言，
CLEAR 砍掉——清历史有 #reset）。
"""

import json
import time

from ..common.log import logger
from ..config import ROOT


def _box(agent_id: str):
    return ROOT / "workspaces" / agent_id / "mailbox.jsonl"


def send(agent_id: str, from_name: str, text: str) -> None:
    """投递一条留言。对方的工作目录可能还没建过（从没被装配过），先补上。"""
    path = _box(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "from": from_name,
            "ts": time.strftime("%H:%M"),
            "text": text,
        }, ensure_ascii=False) + "\n")
    logger.info(f"[Mailbox] {from_name} → {agent_id}: {text[:50]}")


def drain(agent_id: str) -> list:
    """取走全部留言并清空信箱。没有信箱（没人留过言）返回空列表。"""
    path = _box(agent_id)
    if not path.exists():
        return []
    mails = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                mails.append(json.loads(line))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[Mailbox] 读取信箱失败: {e}")
    try:
        path.unlink()  # 签收即清空——看过的留言再看一遍只会浪费上下文
    except OSError:
        pass
    return mails


def format_mails(mails: list) -> str:
    """把留言拼成注入用户消息前的提示块。"""
    lines = "\n".join(f"- 来自 {m.get('from', '?')}（{m.get('ts', '?')}）：{m.get('text', '')}"
                      for m in mails)
    return f"【信箱】你有 {len(mails)} 条来自其他 agent 的留言：\n{lines}\n\n"
