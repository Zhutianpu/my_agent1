# 阶段 10 笔记：Web console

> 对照 CowAgent `channel/web`（70+ 路由全功能控制台，web.py）→
> my-agent 三个文件：web_channel.py（约 200 行）+ 单文件 index.html + factory.py，
> 技术栈换 FastAPI + SSE。这是边界自查第 3 条的兑现验证：**终端换 Web，只重写 channel/**。

## 核心洞察：换皮不换骨为什么能成立

agent 核心（bridge/loop/permission/memory/skills/MCP）一行没改，因为三根管子
在阶段 1~6 就铺好了，web 只是换了个接法：

1. **on_event 事件流**：agent 循环照常发 `agent_start / message_update /
   tool_execution_start / ... / agent_end`。terminal 的 renderer print 到屏幕；
   web 的 renderer 塞进 EventHub 的订阅队列，SSE 端点推给浏览器。
   **agent 不知道自己在跟谁说话**——这就是 channel 抽象的意义。
2. **produce 链**：POST /api/chat → 包装 Context → Bridge().fetch_agent_reply，
   和 terminal 的 input() 路径汇合在同一个方法上。
3. **GATE.confirm_handler 注入点**：阶段 6 说的"web 阶段换异步"在此兑现——
   web_confirm 发布 `confirm_request` 事件后在 threading.Event 上阻塞；
   浏览器点按钮 → POST /api/confirm → resolve_confirm 唤醒它。
   两条线程（agent worker / HTTP handler）靠一个 Event 握手。超时默认拒。

## 事件顺序的一个真坑（测试抓到的）

`agent_end` 是 run() **返回前**发的最后一条事件；而 send() 的兜底
（没流式时把整段答复补推）发生在 run() 返回**之后**。所以 web 端事件序是：

```
agent_start → [message_update × N] → agent_end → [send 兜底 message_update]
```

测试按"agent_end 即结束"捞事件就会漏掉兜底答复。终端没暴露这个是因为
print 没有"捞到某事件就停"的逻辑。契约层面这没错（agent_end 的语义是
"循环跑完了"，不是"输出结束了"），但写消费方时必须知道。

## SSE 的三个工程点

1. **格式**：`data: {json}\n\n`（双换行是一条的分隔）；`ensure_ascii=False`
   让中文不转义，省前端一道解码。
2. **心跳**：队列空 15s 就发 `: ping\n\n`（冒号开头是 SSE 注释），
   防中间代理把静默连接掐了。
3. **多播**：每个 SSE 连接一个订阅队列，EventHub 发布时扇出；
   连接断开 finally 里退订，不泄漏队列。

## 砍掉的（# SIMPLIFIED）

- CowAgent 控制台的全部管理面：workspace 树、memory/skills/MCP 配置页、
  scheduler、logs、auth、多会话……我们只留"聊天"这一件事
- 多实例/凭据/队友派单（channel_factory 的那堆参数）→ P2 再说
- 前端框架与构建工具 → 单文件原生 JS，EventSource + fetch 就够

## 测试策略

- 不起 uvicorn：FastAPI TestClient（httpx）直接打端点
- SSE 产线 `_sse_lines` 是纯生成器 → 离开 HTTP 直接测格式与心跳
- 端到端：Bridge._agents 注入 ScriptedBot 假 agent → POST /api/chat →
  从订阅队列捞事件断言（顺便验证了 send 兜底路径）
- 权限闸：真线程里跑 web_confirm，TestClient POST 答复，断言放行/超时拒
