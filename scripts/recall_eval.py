"""50 轮召回评估：真模型实测"裁剪即蒸馏"的信息保全率。

两层口径（2026-10-28 实测后才分清的，0→9 摆动逼出来的）：
- A 层：事实是否仍存活在**活上下文**里（注回 / 未裁消息 / 模型检索回执）——
  依赖模型临场有没有去捞，会摆动，反映"端到端体验"
- B 层：事实是否留存在**日记文件**里（memory/*.md，append-only）——
  纯管道保真度，确定性指标，不依赖模型行为

跑法：python scripts/recall_eval.py
- 真调 API（约 50 轮对话 + 三十余次蒸馏），DeepSeek 几分钱
- 临时 workspace，跑完即焚，不碰真家；SESSIONS 不落盘
- 双尺都激活：条数尺默认 40；token 尺窗口调小到 8000
  （默认 128K 跑 50 轮短消息根本碰不到 token 尺，调小才能验到它）

产出四个真数：A层召回、B层留存、token 估算峰值 vs 预算、裁剪蒸馏次数。
"""

import os
import re
import sys
import tempfile
import time
from pathlib import Path

# env 覆盖必须抢在 my_agent 任何 import 之前（conf 首次 get 即生效）
os.environ["MODEL_CONTEXT_WINDOW"] = "8000"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from my_agent.agent.initializer import initialize_agent            # noqa: E402
from my_agent.agent.protocol.overflow import proactive_budget      # noqa: E402
from my_agent.agent.tools import TOOLS                             # noqa: E402
from my_agent.bridge.context import Context, ContextType           # noqa: E402
from my_agent.models.bot_factory import create_bot                 # noqa: E402
from my_agent.models.session_manager import SESSIONS, estimate_text_tokens  # noqa: E402

# (事实, 探针正则)——正则兼容摘要模型的格式漂移（实测：9点40 会被写成 9:40）
FACTS = [
    ("我最好的朋友叫小明", r"小明"),
    ("周报每周五下午三点截止", r"周五"),
    ("服务器密码强度要求至少16位", r"16\s*位"),
    ("我的工位在B座7层", r"B\s*座\s*7\s*层"),
    ("项目代号是蓝鲸", r"蓝鲸"),
    ("测试环境域名是 test.bluewhale.internal", r"test\.bluewhale\.internal"),
    ("我对花生过敏", r"花生"),
    ("团队站会每天9点40开始", r"9\s*[点:：]\s*40"),
    ("生产环境禁止直连数据库", r"禁止直连"),
    ("我的导师姓欧阳", r"欧阳"),
]

_FILLER_TOPICS = [
    "递归和迭代的区别", "数据库索引为什么用B+树", "HTTP 长连接的保活机制",
    "进程和线程的切换成本", "TCP 拥塞控制的慢启动", "缓存穿透和缓存雪崩",
    "为什么 Redis 单线程还快", "分布式锁的几种实现",
]


def filler(n: int) -> str:
    """每轮约 300 字的灌水——要足够把 token 估算顶过预算。"""
    topic = _FILLER_TOPICS[n % len(_FILLER_TOPICS)]
    return (
        f"第{n}轮练习：请用一句话给我讲讲{topic}。"
        f"这是连续练习的一部分，不需要展开，一句话即可。"
        f"补充一下背景：我在准备面试，想把基础知识过一遍，"
        f"每轮一个主题，你的回答我会记下来后面统一复习。"
        f"如果涉及 trade-off 可以简单带一句，但不要长篇大论。"
    )


def context_text(session) -> str:
    """活上下文全文本：system prompt + 蒸馏摘要注回 + 未裁消息。"""
    parts = []
    for m in session.messages:
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c)
    return "\n".join(parts)


def main():
    bot = create_bot()
    stats = {"trims": 0, "runs_failed": 0, "token_peak": 0}
    flush_log = []  # (输入预览, 输出预览)——诊断蒸馏器实际行为

    with tempfile.TemporaryDirectory() as ws:
        agent = initialize_agent(bot, agent_id="recall_eval", workspace_dir=ws)
        # 评估只用只读工具：filler 轮模型曾自作主张调 write_file/edit_file
        # （headless 放行），收窄掉——减噪音也防误写
        agent.tools = TOOLS.subset([
            "read_file", "ls", "search_files", "current_time", "memory_search",
            "mcp_time_get_current_time", "mcp_time_echo", "mcp_fetch_fetch",
        ])
        ctx = Context(ContextType.TEXT, kwargs={
            "session_id": "eval", "agent_id": "recall_eval", "on_event": lambda e: None,
        })

        # 拿到 agent 将复用的同一个 session 实例，包两把尺计数
        session = SESSIONS.build_session("eval", "recall_eval")
        orig_count, orig_token = session.discard_exceeding, session.discard_over_tokens

        def counting_count():
            d = orig_count()
            if d:
                stats["trims"] += 1
            return d

        def counting_token(budget):
            d, fits = orig_token(budget)
            if d:
                stats["trims"] += 1
            return d, fits

        session.discard_exceeding = counting_count
        session.discard_over_tokens = counting_token

        # 包蒸馏器：记录每批输入/输出——诊断"事实在哪一代断的"
        orig_flush = agent.memory.flush

        def logged_flush(messages):
            out = orig_flush(messages)
            flush_log.append((str(messages)[:600], (out or "(返回空)")[:400]))
            return out

        agent.memory.flush = logged_flush

        SESSIONS.persist = False  # 评估不留痕

        t0 = time.time()
        for turn in range(1, 51):
            if turn <= 3:
                # 前 3 轮埋 10 个事实（4+3+3）
                lo, hi = (0, 4) if turn == 1 else ((4, 7) if turn == 2 else (7, 10))
                chunk = "；".join(f for f, _ in FACTS[lo:hi])
                query = f"请记住我的这些信息（后面会考你）：{chunk}。"
            elif turn == 50:
                query = "收个尾：我最好的朋友叫什么？项目代号是什么？"
            else:
                query = filler(turn)
            try:
                agent.run(query, ctx)
            except Exception as e:
                stats["runs_failed"] += 1
                print(f"  [turn {turn}] run 失败: {e}")
            est = session.estimate_tokens()
            stats["token_peak"] = max(stats["token_peak"], est)
            if turn % 5 == 0:
                print(f"  ... {turn}/50 轮，当前估算 {est} tokens，已裁剪 {stats['trims']} 次")

        # ---- A 层判定：事实探针是否仍在活上下文 ----
        text = context_text(session)
        survived = [(f, p) for f, p in FACTS if re.search(p, text)]
        # ---- B 层判定：事实探针是否留存在日记里（append-only，管道保真度）----
        diary_files = sorted((Path(ws) / "memory").glob("*.md"))
        diary = "\n".join(f.read_text(encoding="utf-8") for f in diary_files)
        kept = [(f, p) for f, p in FACTS if re.search(p, diary)]
        lost_a = [(f, p) for f, p in FACTS if not re.search(p, text)]
        lost_b = [(f, p) for f, p in FACTS if not re.search(p, diary)]
        budget = proactive_budget(estimate_text_tokens(session.system_prompt))
        summary_alive = session.SUMMARY_MARK in text

        # ---- 证据先行（大体积），结果数压轴（tail 友好）----
        print("\n========== 日记全文 ==========")
        print(diary or "(空)")

        # ---- 诊断：最终注回内容 + 蒸馏器收发记录 ----
        print("\n========== 诊断：最终注回内容 ==========")
        print(session.get_summary() or "(空)")
        print("\n========== 诊断：前 2 次蒸馏收发 ==========")
        for i, (inp, out) in enumerate(flush_log[:2]):
            print(f"-- flush[{i}] 输入: {inp}")
            print(f"-- flush[{i}] 输出: {out}")
        print("\n========== 诊断：最后 2 次蒸馏收发 ==========")
        for i, (inp, out) in enumerate(flush_log[-2:]):
            print(f"-- flush[{len(flush_log) - 2 + i}] 输入: {inp}")
            print(f"-- flush[{len(flush_log) - 2 + i}] 输出: {out}")

        # ---- 结果数压轴：tail 再狠也砍不掉 ----
        print("\n========== 50 轮召回评估结果 ==========")
        print(f"A层(活上下文): {len(survived)}/{len(FACTS)}   B层(日记留存): {len(kept)}/{len(FACTS)}")
        for f, p in lost_a:
            tag = "B层在" if (f, p) in kept else "B层也丢"
            print(f"  [A丢/{tag}] {p}  ({f})")
        for f, p in lost_b:
            print(f"  [B丢-真丢失] {p}  ({f})")
        print(f"蒸馏摘要注回: {'在场' if summary_alive else '不在场'}")
        print(f"token 估算峰值: {stats['token_peak']}（主动道预算 {budget}）")
        print(f"裁剪蒸馏: {stats['trims']} 次；run 失败: {stats['runs_failed']} 次")
        print(f"耗时: {time.time() - t0:.0f}s")

        # ---- 终轮取证：模型被考时到底做了什么（搜没搜？搜到没？答的啥？）----
        print("\n========== 终轮取证：最后 6 条消息 ==========")
        for m in session.messages[-6:]:
            role = m.get("role")
            if m.get("tool_calls"):
                calls = [(tc["function"]["name"], tc["function"]["arguments"][:100])
                         for tc in m["tool_calls"]]
                print(f"[{role}] 调工具: {calls}")
            else:
                print(f"[{role}] {str(m.get('content'))[:300]}")


if __name__ == "__main__":
    main()
