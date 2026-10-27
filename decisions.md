# 决策日志

## D001：bot 无状态，历史归 session 层（2026-10-27）

**决策**：`Bot` 基类只有 `reply(query, context) -> Reply`，不持有历史。
历史存全局唯一的 `SESSIONS`（session_manager 模块），按 `(agent_id, session_id)` 隔离。

**为什么**：CowAgent 简单模式让每个 bot 各抱一个 SessionManager——换模型 = 换柜子 =
历史清零。它的 agent 模式已修正为历史存独立的 memory 层。my-agent 直接采用后者。
状态要存在最长寿的层：对话比 bot 长寿。

**代价**：当前 bot.reply 内部仍会读写全局 SESSIONS（阶段 1 的过渡形态），
到阶段 4 的 agent 循环时，历史的读写将上移到 agent/loop 层，bot 彻底纯化。

## D003：工具循环暂居 bot 内（2026-10-27）→ **阶段 4 已归位**

6 步循环曾暂写在 bot.reply 里作为过渡。阶段 4 已兑现归位：
- bot 契约改为 `chat(messages, tools, on_delta) -> BotResponse`——纯生成器，
  单次、流式、不碰历史（D001 彻底兑现）
- 循环移至 `agent/protocol/loop.py`，主持人角色移至 `agent/protocol/agent.py`
- Bridge 改走 `fetch_agent_reply`（局部 import 破 bridge↔protocol 循环依赖）
- 附带升级：流式输出（on_delta 逐字）+ 会话裁剪改为只在 user 边界下刀
  （工具订单/回执成对保护的落地）

## D004：工具失败一律变错误文本回给模型（2026-10-27）

ToolManager.execute 不抛异常：未知工具/坏 JSON/执行异常全变成
"error: ..." 文本回填。理由：模型能读懂错误文本并自我修正
（换个参数重试），异常只会炸掉整个循环。

## D002：Context/Reply 留在 bridge 包，类型砍到 TEXT/ERROR（2026-10-27）

CowAgent 把它们放 bridge/ 且 models 反向 import（小瑕疵，本应放 common/）。
my-agent 暂保持同构便于对照，类型枚举砍到 TEXT(+IMAGE 预留)/ERROR。
kwargs 口袋机制原样保留——那是精华。
