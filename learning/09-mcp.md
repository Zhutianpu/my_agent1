# 阶段 9 笔记：MCP

> 对照 CowAgent `agent/tools/mcp/`（2265 行）→ my-agent 三个文件约 300 行 + 一个零依赖验收 server。

## 核心洞察（CowAgent 原话级的精华）

**McpTool 适配器**：远程工具包成 BaseTool，模型分不清本地/远程。
ToolManager 一行不改就接入了整个 MCP 生态——这就是"合同模板"的力量：
只要长得像个工具（name/description/params/execute），管你是本地函数还是
另一个进程里的 server。

## stdio 传输的四个工程细节（照搬 CowAgent）

1. **后台线程 + 队列读 stdout**：直接 readline 在 Windows 上没有超时——
   队列 get(timeout=) 才有。这是跨平台超时读的标准解法。
2. **id 配对 + 过期跳过**：上次超时残留的响应会错位，id 不匹配就丢。
3. **通知无 id 不回**：initialized 通知发了就走，不等响应。
4. **一把锁串行化管道**：stdio 只有一根管子，并发写会交错成乱码 JSON。

## 安全三层

- 命令白名单（python/node/npx/uvx/uv）——server 配置不能让你跑任意 exe
- 环境变量过滤（*_KEY/*_TOKEN/*_SECRET 不透传给子进程）
- server 级 risk 配置 → 权限闸（MCP 工具风险自报不了，配置说了算，
  默认 write 弹窗，只读 server 配 "read"）

## 砍掉的（# SIMPLIFIED）

- SSE / Streamable HTTP 传输、OAuth（远程 server 才需要，本地 stdio 够用）
- tools/list 分页游标（本地 server 工具数量一页装得下）
- tool_retrieval 动态加载（工具多时按相关性挂载——我们工具还少）
- CowAgent 的严格环境白名单（只放行安全变量）→ 我们反过来：黑名单过滤敏感变量

## 测试策略

- 适配器层：假 client（不起进程）
- 协议层：真子进程跑 scripts/mcp_time_server.py——零依赖手写 server，
  证明客户端说的是协议本身，不是靠 mcp SDK 兜底
- 全局状态卫生：权限闸 handler 进了 conftest 复位清单（跨文件泄漏真踩到）
