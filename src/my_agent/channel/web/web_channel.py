"""Web channel：FastAPI + SSE（阶段 10）。

契约与 terminal 完全相同（startup/send/produce）。区别只在转播方式：
terminal 的 renderer 把 on_event 事件 print 到屏幕；web 的 renderer 把同一批
事件塞进订阅队列，SSE 端点逐条推给浏览器。agent 核心一行没改——
边界自查第 3 条"终端换 Web → 只重写 channel/"的兑现。

SIMPLIFIED（对照 CowAgent channel/web：70+ 路由的全功能控制台）：
- 单会话单用户、无 auth（本机自用）
- 只有一个聊天页；workspace/memory/skills 管理 API 全砍
- 前端单文件原生 JS，无构建工具

权限闸的缝（阶段 6 留的 GATE.confirm_handler 注入点）在这里兑现成异步版：
浏览器弹确认条，agent 线程在 threading.Event 上等答复，超时默认拒。
"""

import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from ...agent.permission import GATE
from ...bridge.context import Context, ContextType
from ...bridge.reply import ReplyType
from ...common import const
from ...config import conf
from ...models.session_manager import SESSIONS
from ..channel import ChatChannel


# ---------- 事件枢纽：renderer 塞进来，SSE 订阅者领走 ----------

class EventHub:
    """多播队列：每个 SSE 连接一个订阅队列。无订阅者时事件直接丢
    （单用户自用场景：浏览器没连着，事件给谁看？）。"""

    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: dict):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            q.put(event)


HUB = EventHub()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _sse_lines(q: queue.Queue, heartbeat: float = 15):
    """SSE 产线：开场一条 notice + 队列事件逐条推 + 心跳保活（防代理掐线）。"""
    yield _sse({"type": "notice", "data": {"text": "已连接 my-agent"}})
    while True:
        try:
            yield _sse(q.get(timeout=heartbeat))
        except queue.Empty:
            yield ": ping\n\n"


# ---------- 异步权限闸（GATE.confirm_handler 的 web 版） ----------

_pending = None  # {"event": threading.Event, "answer": str}；单用户单 pending


def web_confirm(tool_name: str, args: dict, timeout: float = 120) -> str:
    """浏览器确认条：发布请求事件后阻塞等答复。超时不点 = 拒绝（默认安全）。"""
    global _pending
    box = {"event": threading.Event(), "answer": "n"}
    _pending = box
    HUB.publish({"type": "confirm_request",
                 "data": {"tool_name": tool_name, "arguments": args}})
    box["event"].wait(timeout)
    _pending = None
    return box["answer"]


def resolve_confirm(answer: str):
    """POST /api/confirm 的落点：把浏览器的答复递给正在等的 agent 线程。"""
    if _pending is not None:
        _pending["answer"] = answer if answer in ("y", "a") else "n"
        _pending["event"].set()


# ---------- 转播员：同一份事件字典，不 print 改广播 ----------

class WebRenderer:
    """与 TerminalRenderer 收同一批 on_event 事件，只是去向不同。"""

    def __init__(self):
        self.streamed = False  # 本轮是否已有文本流过（send 兜底用）

    def handle_event(self, event: dict):
        if event.get("type") == "message_update":
            self.streamed = True
        HUB.publish(event)


# ---------- channel 本体 ----------

class WebChannel(ChatChannel):
    def __init__(self, session_id=const.DEFAULT_SESSION_ID):
        self.session_id = session_id
        self.renderer = WebRenderer()
        self._busy = threading.Lock()  # 单用户：上一条没跑完不并发起新 run

    def startup(self):
        GATE.confirm_handler = web_confirm  # 阶段 6 留的缝：换成异步询问器
        port = int(conf().get("web_port", 8765))  # 教训：env 覆盖返回字符串
        print(f"my-agent web console: http://127.0.0.1:{port} （Ctrl+C 退出）")
        import uvicorn
        uvicorn.run(build_app(self), host="127.0.0.1", port=port, log_level="warning")

    def send(self, reply, context):
        if reply.type == ReplyType.ERROR:
            HUB.publish({"type": "error", "data": {"error": reply.content}})
        elif not self.renderer.streamed:
            # 没流过（比如模型没走流式）：整段补推，复用 message_update 事件
            HUB.publish({"type": "message_update", "data": {"delta": reply.content}})

    # ---- 消息分发：命令同步处理，聊天扔 worker 线程 ----

    def dispatch(self, text: str) -> dict:
        """POST /api/chat 的落点。返回即时回执，真正的答复走 SSE。"""
        if text == "#reset":
            SESSIONS.clear_session(self.session_id)
            from ...bridge.bridge import Bridge  # 局部 import 破环（同 terminal）
            Bridge().reset_agent()
            HUB.publish({"type": "notice", "data": {"text": "（对话已清空，身份已重新装配）"}})
            return {"ok": True}
        if text.startswith("#") and text != "#dream":
            HUB.publish({"type": "notice",
                         "data": {"text": f"（未知命令 {text}，目前只有 #reset / #dream）"}})
            return {"ok": True}
        if not self._busy.acquire(blocking=False):
            HUB.publish({"type": "notice", "data": {"text": "（上一条还在处理中…）"}})
            return {"ok": False, "busy": True}
        threading.Thread(target=self._run, args=(text,), daemon=True).start()
        return {"ok": True}

    def _run(self, text: str):
        try:
            if text == "#dream":
                from ...bridge.bridge import Bridge
                agent = Bridge().get_agent(const.DEFAULT_AGENT_ID)
                HUB.publish({"type": "notice", "data": {"text": "🌙 dreaming..."}})
                result = agent.memory.dream() if agent.memory else "（无记忆系统）"
                HUB.publish({"type": "notice", "data": {"text": result}})
                return
            self.renderer.streamed = False
            context = Context(ContextType.TEXT, text, kwargs={
                "session_id": self.session_id,
                "agent_id": const.DEFAULT_AGENT_ID,  # P2 的缝
                "on_event": self.renderer.handle_event,
            })
            self.produce(context)
        finally:
            self._busy.release()


# ---------- FastAPI 装配 ----------

def build_app(channel: WebChannel) -> FastAPI:
    """把 channel 挂进 HTTP 端点。与 startup 分开，测试不起 uvicorn 也能测。"""
    app = FastAPI(title="my-agent web console")
    index = Path(__file__).parent / "static" / "index.html"

    @app.get("/", response_class=HTMLResponse)
    def home():
        return HTMLResponse(index.read_text(encoding="utf-8"))

    @app.post("/api/chat")
    def chat(payload: dict):
        text = str(payload.get("text", "")).strip()
        if not text:
            return {"ok": False}
        return channel.dispatch(text)

    @app.post("/api/confirm")
    def confirm(payload: dict):
        resolve_confirm(str(payload.get("answer", "n")))
        return {"ok": True}

    @app.get("/api/stream")
    def stream():
        q = HUB.subscribe()

        def gen():
            try:
                yield from _sse_lines(q)
            finally:
                HUB.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    return app
