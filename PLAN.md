# my-agent 建造计划（v2：以 CowAgent 为主蓝图复现）

> 2026-10-26 定稿。方向：**以 CowAgent 的架构为主蓝图，逐模块亲手复现**。
> 交互：终端 REPL 为主 + 简约 Web console（核心链验收后再做）。
> 裁剪：voice / translate / 全部 IM channel（微信系、飞书、钉钉等）不做。
> 主蓝图：`D:\work\work_ws\vibe coding something\COPY Cow agent\CowAgent-master`
> 备胎参考（CowAgent 太重时查）：`offer-coach`（工程骨架）、`myself`（功能雏形）

## 含金量策略（为什么这么做）

复现的含金量不在"大"，在"可防守的深度"。三层定位：

- **广度层**：核心链全复现 → 证明"能独立实现一套完整 Agent Harness"
- **深度层**：挑 2~3 个模块做到有测试、有指标、有取舍记录
  （候选：memory 检索——沿用 offer-coach 的 recall@K 评估打法；
   tools 循环——防死循环/预算/截断的测试矩阵）
- **差异化层**：复现中记录 CowAgent 的设计缺陷，成熟的整理成 issue/PR/剖析文章

与 offer-coach 的简历叙事：一深（检索极致）一广（完整 Harness），互补。
决策全程记 decisions 日志（沿用 offer-coach 传统），测试全 FakeProvider 不烧钱。

## CowAgent 消息主链路（复现的总图纸）

```
app.py ──启动──> channel_factory 起 channel（只复现 terminal）
                     │ 收到用户消息
                     ▼
              bridge/bridge.py  ──agent 模式──> bridge/agent_bridge.py
                     │                              │
                     │                              ▼
                     │                    agent/chat/service.py（会话编排）
                     │                              │
                     │                              ▼
                     │                    bridge/agent_initializer.py（装配：
                     │                    记忆/工具/技能/工作区 → 造出 Agent）
                     │                              │
                     │                              ▼
                     │                    agent/protocol/agent.py
                     │                      + agent_stream.py（★工具循环本体）
                     │                              │ 需要生成时
                     ▼                              ▼
              models/bot_factory → models/<厂商>/（Bot.reply 统一接口）
                     │
                     ▼ 回复沿原路返回 channel 显示
```

## 复现纪律（每个模块都走这四步）

1. **读**：读 CowAgent 对应文件，用一两句话写下"这个模块的契约是什么"
2. **画**：默写它的公开接口（类名、方法签名、数据类），不看代码
3. **写**：合上 CowAgent，按接口自己实现
4. **对照**：打开 CowAgent 比对差异，把"它多做了什么、为什么"记进笔记

契约照搬 CowAgent，**内脏允许简化，但每处简化都要在代码注释里标注**
（`# SIMPLIFIED: 原版的 X 未实现，因为 Y`）——简化是决策，不是遗漏。

## 目标结构（目录名直接对齐 CowAgent）

```text
my-agent/
├── app.py                  # 入口：加载配置、起 terminal channel（对齐 app.py）
├── config.py + config-template.json   # 配置系统（简化版）
├── common/                 # log / const / singleton / utils
├── bridge/
│   ├── context.py          # Context 类型：消息载体（77行，照抄思路）
│   ├── reply.py            # Reply 类型：回复载体（31行）
│   └── bridge.py           # 路由：消息 → bot 或 agent
├── models/
│   ├── bot.py              # Bot 基类：reply(query, context) 统一接口（48行）
│   ├── bot_factory.py      # 按配置造 bot（90行）
│   ├── session_manager.py  # 会话历史管理（91行）
│   └── openai_compatible/  # 唯一要实现的厂商（DeepSeek/Kimi 都兼容）
├── channel/
│   ├── channel.py          # Channel 基类：startup / handle / send 契约
│   └── terminal/           # REPL 实现（参照 386 行的 terminal_channel.py）
├── agent/
│   ├── prompt/builder.py   # system prompt 分段组装
│   ├── tools/
│   │   ├── base_tool.py    # 工具基类（251行）
│   │   ├── tool_manager.py # 注册表 + schema 暴露（简化 840→~200行）
│   │   └── <每个工具一个目录>/   # bash/ read/ edit/ ls/ search_files/
│   ├── protocol/
│   │   ├── agent.py        # Agent：持有 model+tools+memory 的执行体
│   │   └── loop.py         # ★工具循环（原版 agent_stream.py 2962 行的简化）
│   ├── memory/             # 三层记忆（先文件式，后加向量）
│   └── skills/             # SKILL.md 加载（loader 361 + manager 519 → 简化）
└── tests/
```

## 分阶段路线（按依赖顺序，一阶段一验收）

### 阶段 0：读懂脊柱（不写代码，1~2 天）✅ 2026-10-27 完成
笔记：[learning/00-spine-reading.md](learning/00-spine-reading.md)（五份契约 + 六条原则）

### 阶段 1：config + common + models ✅ 代码完成，待真机验收
- [x] 简化版 config.py：json 加载 + `conf().get()`（+ .env 密钥优先）
- [x] common/log、common/singleton、common/const
- [x] models/bot.py 基类 + openai_compatible 实现（**决策 D001：bot 无状态，历史归全局 SESSIONS**）
- [x] session_manager：本子+柜子，key=(agent_id, session_id)（P2 的缝已留）
- [x] bridge/context.py + reply.py（TEXT/ERROR 简化版 + kwargs 口袋）
- [x] 6 个 FakeBot 离线测试全过
- [ ] **真机验收**：配好 config.json 后 `python scripts/ask.py "你好"` 有正常回复

### 阶段 2：bridge + terminal channel（能对话）✅ 代码完成，待真机验收
- [x] Context / Reply 数据类（阶段 1 已提前落地）
- [x] Bridge 单例：路由表 + 懒加载缓存 + fetch_reply_content
- [x] Channel 基类（双向契约）+ ChatChannel.produce（同步直调，SIMPLIFIED 掉队列线程池）
- [x] TerminalChannel：REPL 循环 + #exit/#reset + on_event 实况转播员占位
- [x] 5 个离线测试全过（含"同进程多轮历史累积"——补上 ask.py 跨进程失忆的验收）
- [x] **真机验收**（2026-10-27）：多轮历史成立（token 16→36→46 佐证），#exit 正常；
      抓到并修复 bug：未知 # 命令曾被发给模型，现已拦截（+1 测试，共 12 个全过）

### 阶段 3：tools ✅ 代码完成，待真机验收
- [x] base_tool.py：合同模板（name/description/params + execute → ToolResult 成败分离）
- [x] tool_manager.py：注册表 + schemas() 说明书编译 + execute() 失败全变错误文本（D004）
- [x] 5 个内建工具：read_file(分页截断) / write_file / ls / run_command(黑名单+超时) / search_files
- [x] 6 步工具循环（暂居 bot，D003）+ on_event 实况转播接线
- [x] 9 个新测试（含假客户端剧本验证循环两轮、轮数上限防死循环），共 21 个全过
- [ ] **真机验收**：`python app.py` 让它"读一下 PLAN.md 并总结"——应看到 🔧 事件实况

### 阶段 4：agent 循环 ✅ 代码完成，待真机验收
- [x] agent/protocol/agent.py：Agent 主持人（找会话、跑循环、包 Reply）
- [x] agent/protocol/loop.py：6 步循环归位，bot 纯化为 chat()->BotResponse（D003 兑现）
- [x] 流式输出：bot 流式读 + on_delta 逐字回调 + 终端实况转播；防重印（streamed 标记）
- [x] 流式 tool_calls 碎片按 index 拼回完整订单（测试覆盖：参数故意碎两块）
- [x] 会话裁剪改为只在 user 边界下刀 + 孤儿 tool 兜底清理
- [x] 测试改写跟进新契约，20 个全过
- [x] **真机验收**（2026-10-27）：write_file→read_file→回答 三段调用 token 递增正确，
      hello.txt 真实创建；流式逐字输出与工具事件实况显示正常

### 阶段 5：prompt builder + workspace
- [ ] 读 `agent/prompt/builder.py`（1117行）的分段结构：身份/工具说明/记忆/技能/工作区
- [ ] 写自己的 builder：分段组装 system prompt，每段可开关
- [ ] **验收**：换 workspace 目录，agent 行为随之变化

### 阶段 6：memory（以 CowAgent 为准的复现）
> 设计基准：CowAgent `agent/memory/`。核心思想——记忆是可检索的（分块+混合检索
> +memory_search 工具），蒸馏是流水线（消息→日记→核心记忆），向量可降级为关键词。

- [ ] **6a 会话持久化**：jsonl 落盘（key=(agent_id, session_id)），启动时恢复
      （原版 conversation_store SQLite 3161 行 → 简化 jsonl）
- [ ] **6b 三层文件 + 蒸馏流水线**：
      `workspace/memory/YYYY-MM-DD.md`（日记）+ `workspace/MEMORY.md`（核心记忆）；
      flush：消息数超阈值 → LLM 蒸馏写日记；dream：日记汇总进核心记忆（先手动触发）
- [ ] **6c 检索**：chunker（markdown 分块）+ 关键词检索先行；memory_search 工具
      挂进 ToolManager，模型按需查记忆；prompt 注入"最近日记摘要"（依赖阶段 5）
- [ ] **6d（可选）向量增强**：搬 offer-coach 的 embedder（bge-small-zh 本地）；
      provider=None 时保持纯关键词降级（对齐 manager.py 的设计）
- [ ] 不做：deep_dream 定时自动触发、知识图谱、hit_boost 精细调参
- [ ] **验收**：聊 20+ 轮触发蒸馏 → 重启进程 → 问旧事能经 memory_search 召回

### 阶段 7：skills
- [ ] loader.py：扫 skills/ 目录、解析 SKILL.md frontmatter
- [ ] manager.py：按描述注入 prompt、按需加载正文
- [ ] **验收**：扔一个自己写的 SKILL.md 进去，相关提问时 agent 用上它

### 阶段 8（可选）：MCP（以 CowAgent 为准的复现）
> 核心洞察：McpTool 适配器只有 33 行——把远程工具包成 BaseTool，
> 模型分不清本地/远程。厚的是客户端盔甲（三种传输+OAuth），只做 stdio。

- [ ] `agent/tools/mcp/mcp_client.py`：JSON-RPC stdio 客户端（子进程拉起 server、
      initialize 握手、list_tools、call_tool、stderr 抽干、readline 超时）
      ——myself step11 的 MCPClient 是现成底子，对齐 CowAgent 的方法签名
- [ ] `agent/tools/mcp/mcp_tool.py`：McpTool 适配器（33 行近乎照抄，
      名字加 `mcp_<server>_` 前缀防撞名）
- [ ] 挂载点：agent 启动时读 `mcp_servers.json` → 逐 server 握手 →
      工具包成 McpTool → `TOOLS.register()`（ToolManager 一行不改）
- [ ] 安全：命令白名单（只允许 npx/uvx/node/python 等）
- [ ] 不做：SSE/HTTP 传输、OAuth、tool_retrieval 动态加载（工具爆炸时再议）
- [ ] **验收**：`mcp_servers.json` 配 server，启动后工具自动出现在 schemas 里
- [ ] **验收后接入清单**（与 CowAgent 生态对齐）：
      time（myself/mcp_servers/mcp_server_time.py 现成）、
      filesystem（官方 @modelcontextprotocol/server-filesystem）、
      fetch（官方）、sequential-thinking（官方）

### P2 阶段：多 agent（确认要做，核心链验收后开工）
多 agent = N 次单 agent 装配 + 花名册 + 派单 + 信箱。
参照：`agent/registry.py`（花名册）、`routing.py`+`team_addressing.py`（派单）、
`multiagent/transport.py`（信箱）、`tools/agent_delegate`（委托工具）。
- [ ] **核心链阶段就必须留好的四条缝**（后补要拆墙）：
  1. 存储 key 一律 `(agent_id, session_id)`，值先写死 `"default"`
  2. 工作区按 `workspaces/<agent_id>/` 分目录
  3. initializer 签名留 `agent_id=None` 参数
  4. ToolManager 支持按 agent 过滤工具（工具白名单）
- [ ] P2 开工时：registry → 单 agent 多实例 → addressing → transport → delegate 工具

## 明确不复现（红线）

- ❌ 13 个 IM channel、voice、translate、desktop、docker、cow CLI、docs
- ❌ plugins/ 旧命令体系（和 skills 重复）
- ❌ 流式取消/steering/artifact 文件发送（阶段 4 先列清单，默认不要）

## CowAgent 模块取舍清单（复现范围地图）

**整目录删**：voice/ translate/ desktop/ docker/ scripts/ cli/ docs/ plugins/
**channel/**：留 terminal + web + 4 个基类文件；删微信系5个 + feishu/dingtalk/qq/slack/telegram/discord
**models/**：留 bot.py / bot_factory.py / session_manager.py / openai_compatible_bot.py；删 15 个厂商目录
**agent/tools/**：留 bash/read/edit/ls/search_files/current_time/memory/mcp/utils；
  删 send/evolution_undo/browser；暂缓 scheduler/vision/agent_delegate/subagent/env_config
**agent/**：留 protocol/chat(裁团队)/memory/prompt/skills/tools/permission/workspace；
  删 admin.py/routing.py；暂缓 multiagent/team.py/team_addressing.py/registry.py/evolution/knowledge
**依赖**：删 wechatpy/lark-oapi/dingtalk_stream/python-telegram-bot/slack_bolt/discord.py/
  pycryptodome/websocket-client/qrcode/pydub/gTTS/google-generativeai

## 边界的自查三问（沿用，加新东西前必问）

1. "换一家 LLM，哪些文件要动？" → 只能动 `models/`
2. "加一个新工具，要碰几个文件？" → 只新增 `agent/tools/<name>/` 一个目录
3. "终端换成 Web，哪些要重写？" → 只重写 `channel/`

## 风险与对策

| 风险 | 对策 |
|---|---|
| CowAgent 生产代码间接层多，读不动 | 每个文件只读"契约层"（类定义/公开方法），实现细节用到再看 |
| agent_stream.py 2962 行劝退 | 先写 150 行同步版，把原版当"功能菜单"而非"必须达到的形态" |
| 复现变照抄，学完没感觉 | 四步纪律里"画"和"写"必须合上书做；对照时差异必须写成笔记 |
| 简化过头丢掉关键设计 | 每处简化必须注释 `# SIMPLIFIED:` + 原因，验收时回看 |
| 贪阶段 | 一阶段验收绿了才进下一阶段 |
