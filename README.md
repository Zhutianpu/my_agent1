# my-agent

从 0 实现的通用 Agent Harness：模型 / 工具 / 通道 / 记忆全部可插拔的 Python agent 运行时。

写它的动机：搞清楚一个 agent harness 内部到底在发生什么——循环、流式、工具协议、
权限、记忆、子代理、MCP。每个模块都可替换：换模型只动 `models/`，换交互界面只重写 `channel/`。

## 架构

```
channel（终端 / Web）── bridge（Context / Reply 契约）── agent（循环 / 工具 / 记忆）── models（无状态 bot）
```

四层解耦，BotResponse / ToolResult 契约贯穿层间。终端与 Web 控制台（FastAPI + SSE）
复用同一核心，新增模型 / 工具 / 通道不改动既有模块。

## 特性

- **6 步 ReAct 循环**：流式输出、tool_call 碎片拼装、tool_result 按调用 ID 回填
- **权限闸**：工具自报风险分级，写操作需确认（终端逐次 / Web 事件握手，超时默认拒绝）
- **记忆**："裁剪即蒸馏"——超预算消息由 LLM 浓缩进当日日记、摘要注回活上下文；
  关键词检索（memory_search）按需召回
- **多 agent**：子代理派单（独立会话、用完即弃）+ delegate 委托（进对方主会话、可追问）；
  工具集裁剪 + 调用栈检测从结构上杜绝循环派单
- **MCP**：手写 JSON-RPC 2.0 / stdio 客户端（不依赖 SDK），远程工具与本地工具同构；
  子进程命令白名单 + 敏感环境变量过滤
- **上下文护甲**：主动 token 预算裁剪 + 撞墙后按 provider 报错抠真实预算压缩重试；
  Ctrl+C 中断保持 tool_call 协议配对完整

## 数字（都实测过）

- **126 条 pytest 全绿**（FakeProvider，不烧 API 钱），覆盖 11 类故障场景
- 11 个内置工具 / 2 类通道 / 2 个 MCP server 端到端接入
- 50 轮长会话召回评估（`scripts/recall_eval.py`）：埋点 10 条事实，
  30+ 次滚动蒸馏后日记留存 10/10

## 快速开始

```bash
pip install -e .
cp config-template.json config.json   # 填入 open_ai_api_key（任意 OpenAI 兼容服务）
python app.py                          # 默认终端模式
```

Web 控制台：把 `config.json` 里 `"channel"` 改成 `"web"`，访问 `:8765`。

跑测试：`pytest tests`（全离线，无需 API key）

## 目录

| 路径 | 内容 |
|---|---|
| `src/my_agent/` | 全部源码（四层） |
| `tests/` | 126 条测试，按实现阶段组织 |
| `scripts/recall_eval.py` | 50 轮召回评估（真模型，需 API key，A/B 双层口径） |
| `learning/` | 各阶段实现笔记 + 事故复盘 |
| `PLAN.md` / `decisions.md` | 阶段计划与取舍决策日志 |

## 实现方式

架构参照生产级开源 Agent 项目逐模块复现：读契约、自己写、对照记差异，每个取舍进
`decisions.md`。
