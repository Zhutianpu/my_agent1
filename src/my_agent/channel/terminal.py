"""终端 channel：REPL 入口（阶段 6 版：权限闸询问器）。

契约不变：
  startup()：while True 收键盘输入 → 包装 Context → produce
  send()：   Reply → 屏幕

流式防重印（CowAgent terminal_channel 的同款坑）：答案已经通过
message_update 事件逐字打印过了，send() 就不能再印一遍——
用 renderer.streamed 标记判断。

阶段 6：启动时向权限闸注入询问器（GATE.confirm_handler）。
危险操作会在循环中同步弹 input() 问你。web channel（阶段 10）
会注入异步版——这个注入点就是缝。
"""

import json

from ..agent.permission import GATE
from ..bridge.context import Context, ContextType
from ..bridge.reply import Reply, ReplyType
from ..common import const
from ..models.session_manager import SESSIONS
from .channel import ChatChannel


def _terminal_confirm(tool_name: str, args: dict) -> str:
    """权限闸的终端询问器：y=允许一次 / a=此类都允许 / 其他=拒绝（默认安全）。"""
    preview = json.dumps(args, ensure_ascii=False)
    if len(preview) > 200:
        preview = preview[:200] + "..."
    print(f"\n  ⚠️  agent 请求危险操作：{tool_name} {preview}")
    ans = input("  允许？[y=允许一次 / a=此类都允许 / n=拒绝] ").strip().lower()
    return ans if ans in ("y", "a") else "n"


class TerminalRenderer:
    """实况转播员：收听 agent 事件并实时显示。"""

    def __init__(self):
        self.streamed = False  # 本轮是否已有文本流过（防 send 重印）

    def handle_event(self, event: dict):
        etype = event.get("type")
        data = event.get("data", {})
        if etype == "agent_start":
            print("\nAgent: ", end="", flush=True)
        elif etype == "message_update":
            print(data.get("delta", ""), end="", flush=True)
            self.streamed = True
        elif etype == "tool_execution_start":
            if self.streamed:
                print()  # 文本流收尾换行
                self.streamed = False
            args = str(data.get("arguments"))[:200]
            print(f"  🔧 {data.get('tool_name')} {args}")
        elif etype == "tool_execution_end":
            flag = "✓" if data.get("status") == "success" else "✗"
            print(f"  {flag} {data.get('tool_name')}")
        elif etype == "error":
            print(f"\n  ❌ {data.get('error')}")
        elif etype == "agent_end":
            print()  # 收工换行


class TerminalChannel(ChatChannel):
    def __init__(self, session_id=const.DEFAULT_SESSION_ID):
        self.session_id = session_id
        self.renderer = TerminalRenderer()

    def startup(self):
        GATE.confirm_handler = _terminal_confirm  # 权限闸接上终端
        print("my-agent 已启动。输入对话开始，#exit 退出，#reset 清空对话，#dream 沉淀记忆。\n")
        while True:
            try:
                prompt = input("你: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n再见。")
                break
            if not prompt:
                continue
            if prompt == "#exit":
                print("再见。")
                break
            if prompt == "#reset":
                SESSIONS.clear_session(self.session_id)
                # 连装配好的 agent 一起丢：下一条消息重新装配、重编 prompt。
                # 改了 AGENT.md 想立即生效：改完打个 #reset。
                from ..bridge.bridge import Bridge
                Bridge().reset_agent()
                print("（对话已清空，身份已重新装配）\n")
                continue
            if prompt == "#dream":
                # 阶段 7：手动触发"做梦"——最近日记蒸馏进 MEMORY.md
                from ..bridge.bridge import Bridge
                agent = Bridge().get_agent(const.DEFAULT_AGENT_ID)
                if agent.memory:
                    print(f"（🌙 dreaming...）")
                    print(agent.memory.dream(), "\n")
                else:
                    print("（无记忆系统）\n")
                continue
            if prompt.startswith("#"):
                # # 开头但不是已知命令：拦截提醒，不送给模型
                # （真机抓到的 bug："#rest" typo 被当成"我要休息"发给了模型）
                print(f"（未知命令 {prompt}，目前只有 #exit / #reset / #dream）\n")
                continue

            self.renderer = TerminalRenderer()  # 每轮新转播员，重置 streamed
            context = Context(
                ContextType.TEXT,
                prompt,
                kwargs={
                    "session_id": self.session_id,
                    "agent_id": const.DEFAULT_AGENT_ID,  # P2 的缝
                    "on_event": self.renderer.handle_event,
                },
            )
            self.produce(context)

    def send(self, reply: Reply, context: Context):
        if reply.type == ReplyType.ERROR:
            print(f"Agent(错误): {reply.content}\n")
        elif not self.renderer.streamed:
            # 没流式过（比如直接报错收尾）才需要整体打印；流过了只补换行
            print(reply.content)
        print()  # 轮到下一句输入前的空行
