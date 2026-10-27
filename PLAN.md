# my-agent 建造计划（v3：主力项目，全面对齐 CowAgent）

> 2026-10-26 定稿，2026-10-27 v3 对齐升级。方向：**以 CowAgent 架构为主蓝图复现，做主力项目**。
> 交互：终端 REPL + 简约 Web console（阶段 10）。
> 裁剪：voice / translate / 全部 IM channel 不做。
> 主蓝图：`../CowAgent-master`；备胎参考：offer-coach（工程）、myself（功能雏形）
> 工程卫生：git 已初始化（基线 commit 93b1415），config.json/.env 已 gitignore

## 含金量策略

- **广度层**：核心链全复现 → "能独立实现一套完整 Agent Harness"
- **深度层**：2~3 个模块做到有测试、有指标、有取舍记录（候选：memory 检索、tools 循环）
- **差异化层**：记录 CowAgent 的设计缺陷，成熟的整理成 issue/PR/剖析文章
- 决策记 decisions.md，测试全 FakeProvider 不烧钱，每阶段真机验收后 commit

## 复现纪律

1. 读契约 → 2. 默写接口 → 3. 合书实现 → 4. 对照差异记笔记
简化必须注释 `# SIMPLIFIED: 原版做了什么、为什么我没做`。

## CowAgent 消息主链路（总图纸）

```
app.py → channel_factory → channel（terminal / web）
  ↓ Context（kwargs 口袋：session_id / agent_id / on_event）
bridge/bridge.py（路由：查表 + 懒加载缓存）
  ↓ fetch_agent_reply
agent/protocol/agent.py（主持人）→ loop.py（★6 步工具循环）
  ↓ chat(messages, tools, on_delta) -> BotResponse
models/（bot 纯生成器，无状态）
  ↓ Reply 原路返回
旁路装配（initializer）：workspace → memory → tools → skills → 编译 prompt → 造 Agent → 恢复历史
```

## 目标结构（对齐 CowAgent 命名）

```text
my-agent/
├── app.py / config-template.json / decisions.md / learning/ / tests/
├── src/my_agent/
│   ├── config.py             # json + .env（简化版）
│   ├── common/               # log / singleton / const
│   ├── bridge/               # context / reply / bridge（路由）
│   ├── models/               # bot(纯生成器) / bot_factory / session_manager / openai_compatible_bot
│   ├── channel/              # channel 基类 / terminal / (阶段10) web
│   └── agent/
│       ├── initializer.py    # 装配间（阶段 5 成立）
│       ├── prompt/builder.py # 编译式 system prompt
│       ├── workspace/        # workspaces/<agent_id>/ 目录与模板
│       ├── protocol/         # agent.py + loop.py（循环本体）
│       ├── permission/       # 权限闸（阶段 6）
│       ├── tools/            # base_tool / tool_manager / 内建工具 / mcp/
│       ├── memory/           # 持久化 + 蒸馏流水线 + 混合检索（阶段 7）
│       ├── skills/           # SKILL.md 加载（阶段 8）
│       └── subagent/         # 子代理（阶段 11，P2 多 agent 的跳板）
└── scripts/
```

## 已完成

### 阶段 0：读懂脊柱 ✅ 2026-10-27
笔记：learning/00-spine-reading.md（五份契约 + 六条原则）

### 阶段 1~4 ✅ 2026-10-27（全部真机验收通过，20 测试，commit 93b1415）
- config/common/models（D001 bot 无状态、历史归全局 SESSIONS）
- bridge + terminal channel（真机抓 bug：未知 # 命令已拦截）
- tools：合同模板 + 注册表 + 5 内建工具（D004 失败变错误文本）
- 循环归位 agent/protocol + 流式输出 + user 边界裁剪（D003 兑现）

## 待做（按依赖顺序）

### 阶段 5：prompt builder + workspace + 装配间 ✅ 2026-10-27（测试 33 绿，待真机验收）
> 对齐 CowAgent `agent/prompt/builder.py` + `agent/workspace` + `bridge/agent_initializer.py`

- [x] workspace：`workspaces/<agent_id>/` 目录（P2 的缝落地），内置模板文件
      `AGENT.md`（身份）/ `USER.md`（用户画像）/ `MEMORY.md` + `memory/` 子目录
      ——对齐 ensure_workspace + load_context_files（模板砍到 3 个，RULE 并进 AGENT，BOOTSTRAP 不做）
- [x] prompt/builder.py：分段编译 system prompt（工具 / workspace 说明 / 上下文文件 /
      运行时信息），每段"存在即编译"；记忆段、技能段坑位已留（阶段 7/8 接入不改 builder）
- [x] agent/initializer.py：装配间独立（备料→编译→总装），签名 `agent_id=None`（P2 的缝）
- [x] 补两个工具：edit_file（精确替换，唯一性校验）+ current_time
- [x] Agent 注入编译后 prompt，每次 run 刷新 session 第 0 条；#reset 连 agent 一起重装
- [ ] **真机验收**：改 AGENT.md 后 #reset，agent 自我认知变化；workspaces/default/ 目录生成

### 阶段 6：permission 权限闸 ✅ 2026-10-27（测试 41 绿，待真机验收）
> 对齐 CowAgent `agent/permission`，交互式简化（静态政策闸 982 行 → 交互闸 ~80 行）

- [x] Decision(allowed, reason) 契约照搬；工具自报风险级（BaseTool.risk：
      read 自动放行 / write 首次问用户）——SIMPLIFIED: 不做 bash 静态分析
- [x] 危险操作首次执行前问 y=一次/a=此类都允许/n=拒绝；remembered 集合进程内记住
- [x] 拒绝变错误文本回填模型（D004 延伸，同构 CowAgent _permission_denial）
- [x] 审计进 run.log；闸挂在 ToolManager.execute 必经之路，loop 一行不改；
      handler 由 channel 注入（headless 无 handler = 放行，web 阶段换异步）
- [ ] **真机验收**：agent 要写文件时先问你；a 后同类不再问；n 后模型换方案

### 阶段 7：memory（CowAgent 版）✅ 7a/7b/7c 2026-10-27（测试 52 绿，待真机验收）
> 对齐 `agent/memory/`：记忆是可检索的，蒸馏是流水线，向量可降级

- [x] 7a 会话持久化：jsonl 落盘（workspaces/<agent_id>/sessions/，整写），启动恢复，
      #reset 连磁盘一起清；测试经 conftest 关持久化防跨运行污染
- [x] 7b 蒸馏流水线：**裁剪即蒸馏**（照搬 CowAgent 触发设计）——discard_exceeding
      返回被裁消息 → LLM 蒸馏写 memory/YYYY-MM-DD.md；#dream 手动触发日记→MEMORY.md
      （SIMPLIFIED: 同步蒸馏、无哈希去重、无定时器）
- [x] 7c 检索：行窗口重叠 chunker + 关键词打分（向量缺席时的 CowAgent 降级档）；
      memory_search 工具（装配间 bind 数据源）；prompt 注入最近日记
      （阶段 5 builder 坑位兑现，builder 本体未改结构）
- [ ] 7d（可选，未做）向量增强：搬 offer-coach embedder
- [ ] 不做：deep_dream 定时器、知识图谱、hit_boost 调参
- [ ] **真机验收**：聊几轮 → 退出重开 → 历史还在；CONVERSATION_MAX_MESSAGES=8
      聊十几轮 → memory/日期.md 出现；#dream → MEMORY.md 更新；问"我之前说过X" → 它用 memory_search

### 阶段 8：skills
> 对齐 `agent/skills/`（loader 361 + manager 519 → 简化）

- [ ] loader.py：扫 `skills/` 目录、解析 SKILL.md frontmatter（name+description+正文）
- [ ] manager.py：描述注入 prompt（走 builder 分段）、命中时按需加载正文
- [ ] **验收**：扔一个自建 SKILL.md 进去，相关提问时 agent 用上它

### 阶段 9：MCP（CowAgent 版）
> 核心洞察：McpTool 适配器 33 行——远程工具包成 BaseTool，模型分不清本地/远程

- [ ] mcp_client.py：JSON-RPC stdio 客户端（myself step11 底子，对齐 CowAgent 签名）
- [ ] mcp_tool.py：适配器（`mcp_<server>_` 前缀防撞名）
- [ ] 挂载：initializer 里读 mcp_servers.json → 握手 → 注册进 ToolManager（它一行不改）
- [ ] 安全：命令白名单（npx/uvx/node/python）
- [ ] 不做：SSE/HTTP 传输、OAuth、tool_retrieval 动态加载
- [ ] **验收**：配 time server（myself/mcp_servers/mcp_server_time.py 现成），工具自动出现
- [ ] 后续接入：filesystem / fetch / sequential-thinking（官方 server）

### 阶段 10：简约 Web console
> 对齐 `channel/web` 的位置，技术栈换 FastAPI + SSE（比 web.py 现代）

- [ ] channel_factory 成立（app.py 按配置起 terminal 或 web——对齐 CowAgent 入口）
- [ ] channel/web/：FastAPI + SSE 流式推送（复用 on_event 机制，web 转播员）
- [ ] 简约前端：单页聊天窗（消息流 + 工具事件展示），无构建工具，原生 JS
- [ ] **验收**：浏览器聊天与终端同行为；自问三问第 3 条"只重写 channel/"得到验证

### 阶段 11（可选）：subagent 子代理
> 对齐 `agent/subagent` + `tools/subagent`；myself step9 经验；P2 多 agent 的跳板

- [ ] subagent 工具：主 agent 派单，子代理独立 messages（上下文隔离）、跑完回总结
- [ ] 工具白名单（ToolManager 按角色过滤——P2 的缝兑现）
- [ ] 铁律：子代理拿不到 dispatch（防套娃）
- [ ] **验收**："派 scout 查一下 X，派 builder 把结果写进文件"自动完成

### 循环护甲（二期，穿插在有空时）
- [ ] 空响应重试：模型返回空时注入"请明确回复"再问一次（CowAgent 1027~1076 行），用完 pop
- [ ] 取消：Ctrl+C 中止当前 run（KeyboardInterrupt 接进循环）
- [ ] 模型 fallback：主模型持续失败时切备用（run 内粘性）

### P2 阶段：多 agent
多 agent = N 次单 agent 装配 + 花名册 + 派单 + 信箱。
参照：registry.py（花名册）/ routing.py+team_addressing.py（派单）/
multiagent/transport.py（信箱）/ tools/agent_delegate（委托工具）。
四条缝已留：(agent_id,session_id) key ✅ / workspaces 分目录（阶段 5 落地）/
initializer 签名（阶段 5 落地）/ 工具白名单（阶段 11 兑现）。

## 明确不复现（红线）

- ❌ 13 个 IM channel、voice、translate、desktop、docker、cow CLI、docs
- ❌ plugins/ 旧命令体系
- ❌ steering（运行中插话）、artifact 文件发送、evolution、knowledge 图谱

## 边界自查三问

1. 换 LLM → 只能动 models/
2. 加工具 → 只新增一个文件 + 注册一行
3. 终端换 Web → 只重写 channel/

## 风险与对策

| 风险 | 对策 |
|---|---|
| CowAgent 间接层多读不动 | 只读契约层，实现细节用到再看 |
| 简化过头丢关键设计 | 每处简化注释 `# SIMPLIFIED:` + 原因 |
| 贪阶段 | 一阶段验收绿了 + commit 才进下一阶段 |
| config.json 泄露 | 已 gitignore（2026-10-27），commit 前 git status 自查 |
