# my-agent 架构速览

> 写给第一次打开这个仓库的人（也包括三个月后的我自己）。
> 目标：15 分钟内知道"一条消息走完仓库的哪几站"，以及每个阶段为什么这么切。

---

## 一句话概括

这是一个**从零复现的 Agent Harness**——不是调用现成框架，而是把"模型 + 工具 + 记忆 + 技能"
这套循环亲手搭一遍。蓝图参照 CowAgent，裁剪掉了所有 IM 通道、语音、翻译等外围，
只留核心链路，并通过终端与 Web 两个 channel 暴露出来。

---

## 一、一条消息的旅程

用户在终端敲下一行字，到屏幕上出现回复，中间经过这些站：

```
app.py
  └─ channel_factory            按 config 选终端或 Web
      └─ channel（terminal / web）
          ↑↓  Context{k session_id, agent_id, on_event}
      └─ bridge/bridge.py       路由：查表 + 懒加载缓存
          └─ agent/protocol/agent.py    主持人
              └─ loop.py                ★ 工具循环本体
                  └─ models/            bot 是纯生成器，无状态
```

返回时**原路折返**：Reply 对象顺着调用栈回去，channel 负责把它变成终端字符或 SSE 事件。

### 关键设计：状态不在 bot 里

`models/` 下的 bot 是**无状态的纯生成器**——给它 messages 和 tools，它吐出 token 或工具调用。
所有对话历史挂在全局 `SESSIONS` 里，以 `(agent_id, session_id)` 为键。
这一条决定了后面所有能力都是可插拔的：换模型只动 `models/`，加工具只加一个文件。

---

## 二、启动时的旁路装配

真正"造出"一个 agent 的，不是上面那条主链路，而是旁路：

```
initializer（装配间）
  1. workspace   → 确保 workspaces/<agent_id>/ 目录与模板文件存在
  2. memory      → 恢复历史 / 接入蒸馏与检索
  3. tools       → 注册内建工具 + MCP 远程工具
  4. skills      → 扫描 skills/*/SKILL.md，收集描述清单
  5. prompt      → 分段编译 system prompt
  6. 造 Agent    → 注入 prompt，恢复历史会话
```

装配间独立成文件，签名带 `agent_id=None`——**这是多 agent 的预留缝**：
将来 N 个 agent 就是跑 N 次这个装配流程，各自一个 workspace 目录。

---

## 三、工具循环（loop.py，整个项目的心脏）

一次 `run()` 大致是六步：

1. 拿消息（必要时先裁剪上下文）
2. 调模型
3. 若模型要调工具 → 交给 ToolManager 执行
4. 执行结果（成功内容或**错误文本**）回填进消息列表
5. 回到第 2 步，直到模型不再调工具
6. 返回最终回复

**踩过的坑，写进契约的一条**：工具失败不抛异常、不中断循环，
而是变成一段**错误文本**回填给模型，让模型自己纠错换方案。
（记在 `decisions.md` 的 D004）

---

## 四、四个贯穿全局的机制

### 1. 权限闸（permission）

挂在 `ToolManager.execute` 这条必经之路上，**loop 一行都不用改**。
工具自报风险级：读操作自动放行，写操作首次执行先问用户。

- `y` → 这一次允许
- `a` → 这类操作以后都允许（进程内记住）
- `n` → 拒绝（同样变错误文本回填）

终端用同步 input 提问，Web 用异步事件 + `threading.Event` 唤醒。

### 2. 记忆（memory）

三层：

| 层 | 载体 | 触发 |
|---|---|---|
| 会话 | `sessions/*.jsonl` | 每轮落盘，启动恢复 |
| 日记蒸馏 | `memory/YYYY-MM-DD.md` | 上下文被裁时，把丢弃的消息交给 LLM 蒸馏 |
| 长期 | `MEMORY.md` | `#dream` 手动把日记沉淀进去 |

检索走**降级档**：行窗口重叠分块 + 关键词打分（向量缺席时的可用方案）。
模型侧通过 `memory_search` 工具主动查询，prompt 里另外注入最近几天的日记。

> 设计上的一个关键洞察：**裁剪即蒸馏**。既然超出窗口的消息注定要丢，
> 那就在丢弃的那一刻顺手让它"转化为记忆"，而不是等定时器。

### 3. 技能（skills）

两段式加载，这是精髓：

- **prompt 里只放**：技能名 + 一句话描述 + 文件路径
- **正文不进 prompt**：模型判断需要时，才用 `read_file` 去读 `SKILL.md`

于是技能可以无限加而不撑爆上下文。纪律写在 prompt 的技能段里：
"技能不是工具，唯一用法是 read_file 读 SKILL.md"。

### 4. MCP

远程工具通过 `McpTool` 适配器包成 `BaseTool`——**模型分不清本地和远程**。
JSON-RPC over stdio，命名加 `mcp_<server>_` 前缀防撞名，单个 server 挂掉不拖累别人。

---

## 五、分阶段推进的逻辑

阶段不是按"文件多少"切的，而是按**依赖**切的：

```
阶段0  读懂脊柱（先默写契约，再动手）
  ↓
阶段1~4  config → models → bridge/channel → tools → 循环归位
  ↓
阶段5  workspace + prompt builder + 装配间   ← 把散件组装起来
  ↓
阶段6  permission                            ← 挂在 tool 必经之路
阶段7  memory                                ← 依赖 session 与 prompt 坑位
阶段8  skills                                ← 依赖 prompt 最后坑位
阶段9  MCP                                   ← 依赖 tool 注册表
阶段10 web channel                           ← 验证"只重写 channel 层"
阶段11 subagent（可选）
```

每一阶段的验收标准都是**真机跑一遍**，绿了才 commit，才进下一阶段。
测试全用 FakeProvider，不烧钱。

---

## 六、边界自查三问

项目进行中反复用来校验结构是否还在轨：

1. **换一个 LLM，要改几个文件？** → 只改 `models/`
2. **加一个工具，要动几处？** → 新增一个文件 + 注册一行
3. **终端换成 Web，要重写什么？** → 只重写 `channel/`

三个答案都成立，说明抽象是对的；有一个变形了，说明哪层被污染了。

---

## 七、明确不做的事

不是遗漏，是**主动划线**：

- ❌ 十几个 IM channel、语音、翻译、桌面端、Docker、CLI 工具、文档站
- ❌ 插件旧命令体系、steering、artifact 文件发送、知识图谱
- ❌ 所有"能演示但会稀释核心链路"的功能

复杂度是债。每一处简化都在代码里留了 `# SIMPLIFIED:` 注释，
写明**原版做了什么、为什么我没做**——否则三个月后连自己都骗不过。

---

## 附：怎么跑起来

```bash
# 终端模式（默认）
python app.py

# Web 模式：config.json 里把 "channel" 改成 "web"
python app.py
# 然后浏览器打开提示的地址

# 测试
pytest
```

没配 `config.json` 的话，先复制 `config-template.json` 改成自己的。
`config.json` 和 `.env` 已在 `.gitignore` 里，不会误提交。

---

*最后更新：2026-10-27 · 十重*
