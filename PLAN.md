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

### 阶段 5：prompt builder + workspace + 装配间 ✅ 2026-10-27（测试 33 绿，真机验收过）
> 对齐 CowAgent `agent/prompt/builder.py` + `agent/workspace` + `bridge/agent_initializer.py`

- [x] workspace：`workspaces/<agent_id>/` 目录（P2 的缝落地），内置模板文件
      `AGENT.md`（身份）/ `USER.md`（用户画像）/ `MEMORY.md` + `memory/` 子目录
      ——对齐 ensure_workspace + load_context_files（模板砍到 3 个，RULE 并进 AGENT，BOOTSTRAP 不做）
- [x] prompt/builder.py：分段编译 system prompt（工具 / workspace 说明 / 上下文文件 /
      运行时信息），每段"存在即编译"；记忆段、技能段坑位已留（阶段 7/8 接入不改 builder）
- [x] agent/initializer.py：装配间独立（备料→编译→总装），签名 `agent_id=None`（P2 的缝）
- [x] 补两个工具：edit_file（精确替换，唯一性校验）+ current_time
- [x] Agent 注入编译后 prompt，每次 run 刷新 session 第 0 条；#reset 连 agent 一起重装
- [x] **真机验收**：改 AGENT.md 后 #reset，agent 自我认知变化；workspaces/default/ 目录生成 ✅

### 阶段 6：permission 权限闸 ✅ 2026-10-27（测试 41 绿，真机验收过）
> 对齐 CowAgent `agent/permission`，交互式简化（静态政策闸 982 行 → 交互闸 ~80 行）

- [x] Decision(allowed, reason) 契约照搬；工具自报风险级（BaseTool.risk：
      read 自动放行 / write 首次问用户）——SIMPLIFIED: 不做 bash 静态分析
- [x] 危险操作首次执行前问 y=一次/a=此类都允许/n=拒绝；remembered 集合进程内记住
- [x] 拒绝变错误文本回填模型（D004 延伸，同构 CowAgent _permission_denial）
- [x] 审计进 run.log；闸挂在 ToolManager.execute 必经之路，loop 一行不改；
      handler 由 channel 注入（headless 无 handler = 放行，web 阶段换异步）
- [x] **真机验收**：agent 要写文件时先问你；a 后同类不再问；n 后模型换方案 ✅
      （阶段 8 周报场景 + 阶段 11 子代理写文件场景两次验证）

### 阶段 7：memory（CowAgent 版）✅ 7a/7b/7c 2026-10-27（测试 52 绿，真机验收过）
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
- [x] **真机验收**：重开历史恢复 9 条 ✅；裁剪蒸馏出 memory/2026-10-27.md ✅；
      #dream → MEMORY.md 更新 237 字符 ✅；问"我朋友叫什么" → 从 MEMORY.md 注入层
      直接答出（分层设计：MEMORY.md 自动进 prompt，memory_search 管更老的日记）✅

### 阶段 8：skills ✅ 2026-10-27（测试全绿，真机验收过：写周报时自动读 SKILL.md 并按格式输出）
> 对齐 `agent/skills/`（loader 361 + manager 519 → 简化到 ~120 行）

- [x] loader.py：扫 `skills/<技能名>/SKILL.md`、解析 frontmatter（手写 --- 围栏解析，
      只认 name/description，不引 PyYAML；递归/缓存/元数据全砍）
- [x] manager.py：出描述清单进 prompt（builder 最后坑位兑现）；
      正文不进 prompt——纪律写死在技能段："技能不是工具，唯一用法是 read_file 读 SKILL.md"
- [x] 预置演示技能 workspaces/default/skills/weekly-report/
- [x] **真机验收**："帮我写周报" → agent 主动 read_file 读 SKILL.md 并按三段式输出 ✅
      （还超额完成：主动去 git log 核实本周实际工作；触发了权限闸 y/a 流程）
- [x] 附带真机大修复：蒸馏时机挪到循环前 + 摘要注回活上下文
      （对齐 CowAgent context_summary_callback，修复"周报失忆"事件）

### 阶段 9：MCP（CowAgent 版）✅ 2026-10-27（测试 66 绿，真机验收过：握手→接入2工具→mcp_time_echo 端到端）
> 核心洞察兑现：McpTool 适配器——远程工具包成 BaseTool，模型分不清本地/远程

- [x] mcp_client.py：JSON-RPC 2.0 stdio 客户端（换行分隔 JSON；后台线程+队列
      做跨平台超时读；握手 initialize→notifications/initialized；id 配对、
      通知跳过、过期 id 跳过；一把锁串行化管道）
- [x] mcp_tool.py：适配器（`mcp_<server>_` 前缀防撞名，远程调用用原名）；
      注册的是实例不是类（ToolManager.register 升级兼容两种）
- [x] 挂载：initializer 读 mcp_servers.json（mcpServers 格式）→ 握手 → 注册；
      单 server 挂了不拖累别人；#reset 重连；app 退出 shutdown_all
- [x] 安全：命令白名单（python/node/npx/uvx/uv）+ 敏感环境变量不透传 +
      server 级 risk 配置（默认 write 弹窗，read 放行）
- [x] 零依赖验收 server：scripts/mcp_time_server.py（手写协议，不依赖 mcp SDK）
- [ ] 不做：SSE/HTTP 传输、OAuth、tool_retrieval 动态加载、分页游标
- [x] **真机验收**：配好 mcp_servers.json → 握手 → 接入 2 个工具 →
      mcp_time_echo 远程回显端到端通 ✅（"现在几点"走了本地 current_time——
      描述重叠时模型自己挑，前缀只防注册撞名、不管选择偏好，属预期行为）

### 阶段 10：简约 Web console ✅ 2026-10-27（测试 77 绿，真机验收过：页面/SSE/冒烟通过，浏览器交互用户确认）
> 对齐 `channel/web` 的位置，技术栈换 FastAPI + SSE（比 web.py 现代）

- [x] channel_factory 成立（app.py 按配置起 terminal 或 web——对齐 CowAgent 入口；
      config "channel": "terminal" | "web"，默认 terminal）
- [x] channel/web/：FastAPI + SSE 流式推送（复用 on_event 机制，web 转播员：
      同一份事件字典，不 print 改广播；EventHub 多播队列 + 心跳保活）
- [x] 权限闸的缝兑现：web_confirm 异步询问器（confirm_request 事件 → 浏览器确认条
      → POST /api/confirm → threading.Event 唤醒 agent 线程；超时默认拒）
- [x] 简约前端：单页聊天窗（消息流 + 工具事件展示 + 确认条），无构建工具，原生 JS
- [x] 砍：auth、多会话、workspace/memory/skills 管理 API、上传、前端框架
- [x] **真机验收**：config.json 加 "channel": "web" → 浏览器聊天 ✅
      （页面 200 / SSE 已连接 / 浏览器交互用户确认；三问第 3 条"只重写 channel/"兑现：
      agent 核心一行未改，事件流/权限闸注入点原样复用）

### 阶段 11：subagent 子代理 ✅ 2026-10-28（测试 97 绿，真机验收过）
> 对齐 `agent/subagent` + `tools/subagent`；P2 多 agent 的跳板

- [x] subagent 工具：主 agent 派单，子代理独立 session（用完即弃）、
      无 memory 不落盘、跑完回总结——父上下文只见派单和结论
- [x] 工具白名单：ToolManager.subset 按模板裁剪（P2 的缝兑现）；
      内置 general-purpose（全工具）+ explore（只读）；权限闸子集自动继承
- [x] 铁律：BLOCKED_TOOLS 扣死 subagent——子代理工具集里没有派单工具，
      结构上不可能套娃（SIMPLIFIED：砍了 CowAgent 的深度计数双保险）
- [x] 预算减半（max_turns = parent // 2）；SIMPLIFIED：顺序执行无并发超时、
      无用户模板、无事件转播
- [x] **真机验收**：派 explore 查 PLAN.md + 派 general-purpose 写 待办.txt ✅
      （角色路由正确；子代理写文件权限闸照样弹——派单不是权限后门；
      父 agent 用自己的话转述）。真机抓到预算问题：裸减半 8→4 饿死 explore，
      修复为 max(6, parent//2) 保底

### 循环护甲（二期）✅ 2026-10-28（测试 87 绿，真机验收过）
- [x] 空响应重试：模型返回空时注入"请明确回复"再问一次（对齐 CowAgent
      agent_stream.py 1027~1076），用完 pop 不进历史；重试给 tool_calls 落回工具路径；
      SIMPLIFIED: 砍 allow_empty_response（定时任务专用）
- [x] 取消：Ctrl+C 接进循环两层（loop 内接住正常返回 / agent.run 兜底不杀应用）；
      中断补齐剩余 tool_call 的"已中断"结果（配对完整是 API 硬要求，cancel.py 同款）
- [x] 模型 fallback：config "fallback_model"（默认关）；主模型抛错 → run 内粘性
      切备用重试一次；create_bot(model=...) 支持覆盖（自有设计，非 CowAgent 蓝图）
- [x] 顺手修测试污染：工厂测试不再假设真机 config（env 钉死，同 env 字符串同族教训）
- [x] **真机验收** ✅ 2026-10-28：长任务中途 Ctrl+C → 中断提示 + 下一句还能聊 ✅；
      fallback_model 填上 + model 故意改错 → 出切换提示且正常回答 ✅

### 循环护甲（三期）：上下文溢出恢复 ✅ 2026-10-28（测试 125 绿，待真机验收）
> 对齐 agent_stream.py 被动道（_overflow_input_budget :2605 /
> _smart_compact_to_budget :2632 / 只重试一次 :1874）+ _trim_messages :2785。
> 笔记：learning/loop-armor.md 三期段。至此"我的 agent 怎么不死"叙事完整。

- [x] overflow.py：判型（11 标记 + OpenAI 下划线错误码超集）+
      报错抠真实预算（两正则 + ×0.9 余量）+ 主动预算（窗口×0.8 − system）
- [x] token 估算（CJK ×1.5 / ASCII ÷4，对齐 _estimate_text_tokens）+
      Session.discard_over_tokens：先截断老工具结果（6000→500），
      不够再按 user 边界整轮丢；最后一轮永远保留
- [x] 被动道接线：loop 判型抛 ContextOverflowError **抢在 fallback 前**
      （换模型救不了溢出）→ agent 压缩+蒸馏+只重试一次 →
      压不动清内存保磁盘，"请重新描述需求"
- [x] 顺手修：空响应催促注入改 finally pop（异常路径不留假 user 消息）
- [x] SIMPLIFIED：窗口回退一级（config model_context_window 默认 128000）、
      无图片/块结构估算、清内存后下次成功保存仍覆盖磁盘（jsonl 整写）
- [ ] **真机验收**：config 塞小 window 看主动道裁剪+蒸馏不断片；
      被动道靠离线测试担保（真 overflow 烧 64K+ token 不值当）

### P2 阶段：多 agent ✅ 2026-10-28（测试 110 绿，真机验收过）
> 多 agent = N 次单 agent 装配 + 花名册 + 派单 + 信箱。
> 参照：registry.py（花名册）/ routing.py（路由）/
> multiagent/transport.py（信箱）/ tools/agent_delegate（委托工具，719 行）。
> 四条缝全部兑现：(agent_id,session_id) key / workspaces 分目录 /
> initializer 签名 / 工具白名单。笔记：learning/12-multi-agent.md

- [x] roster.py：config.json "agents" 列表 → AgentProfile(id/name/description)，
      现读现生效，坏条目跳过；default 永远在册
- [x] agent_delegate 工具：delegated_prompt 包装（来源署名 + "结果返回给委托方"）；
      委托进对方**主会话**（记得住协作，#use 切过去能接着聊——与 subagent 用完即弃相对）
- [x] 循环防护结构级：被派单者工具集摘 agent_delegate（阶段 11 同一招），
      深度计数多余；补"在跑栈"拒派给正在干活的 agent（防自派单会话嵌套），
      栈顶顺带当自动署名
- [x] mailbox.py + agent_message 工具：jsonl 信箱，上线 drain 拼进本轮用户消息；
      分工写进说明书（要结果 delegate / 知会 message）
- [x] 终端路由：#agents 花名册 / #use <id> 切换（历史各自独立）；
      #reset/#dream 改为对当前 agent 生效
- [x] SIMPLIFIED：砍 workspace/model/skills 档案字段、max_depth/trace/三 mode、
      socket 传输、并发派单、事件转播、channel 绑定路由
- [x] **真机验收** ✅ 2026-10-28：派单+闸弹窗+转述 ✅ / #use 切换+主会话记忆
      （builder 跨重启复述委托、主动提划掉旧待办）✅ / 工具自检 write_file 恢复 ✅
      / 信箱收发+签收 ✅。真机抓 2 bug 并修复：① subset 生成器耗尽（set 写在
      推导式 if 里每次迭代重求值，白名单裁到只剩 read_file——阶段 11 传 list
      可重复消费潜伏三期；测试只有反向断言漏网，补正向断言）② 测试 drain 真机
      信箱（conftest 加 mailbox 沙箱，污染家族第四员）

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
