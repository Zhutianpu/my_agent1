# 阶段 11 笔记：subagent 子代理

> 对齐 CowAgent `agent/subagent/`（runner 381 + templates 219）+
> `agent/tools/subagent/subagent.py`（391）→ my-agent 三个文件约 230 行。

## 核心洞察：派单的全部意义是上下文隔离

CowAgent runner.py 的卷首语值得默写：

> The parent's context only ever sees the spawn call and the returned summary.
> Everything the sub agent read, ran and discarded on the way stays out,
> **which is the point of spawning one at all.**

子代理不是"分身"，是"外包"：它读 20 个文件、跑 10 条命令，父上下文里
这些一条都不留——回来的只有一份总结。这解决的是上下文窗口的通货膨胀。

落地三件套（我们版本）：
- **独立 session**：`subagent_<uuid>`，跑完 `clear_session`，内存磁盘都不留
- **无 memory**：`memory=None` + `persist_session=False`（Agent 新参数）——
  子代理不蒸馏、不落盘，它的历史只属于这次派单
- **工具白名单**：模板裁剪出的注册表子集（`ToolManager.subset`）

## 铁律的实现：结构上不可能，比计数器可靠

CowAgent 防套娃有双保险：BLOCKED_TOOLS 扣掉 subagent + contextvars 深度计数。
我们只留第一道：**子代理的工具集里根本没有派单工具，递归无从发起**——
深度计数管的是"允许嵌套但限制层数"，我们干脆不允许，计数器就是冗余。

权限同理：白名单子集是 ToolManager 级裁剪，execute 里的权限闸自动继承——
子代理写文件照样弹确认。**派单不能成为绕过权限的后门**（CowAgent 同款原则，
它靠 permission_mode 继承，我们靠闸的位置在 ToolManager）。

## 预算减半

`max_turns = parent // 2`（照搬 CowAgent max_steps 减半的注释思想）：
子任务按定义是整体对话的一小块，且从空上下文出发，
不该跑得比派它的整场对话还久。测试用"永远返回 tool_calls 的 bot"
逼出了"最大工具轮数 4"的警告——预算生效的铁证。

## 砍掉的（# SIMPLIFIED）

| CowAgent | 我们 | 理由 |
|---|---|---|
| ThreadPoolExecutor 并发 + 超时 + wrap-up | 顺序执行 | 权限闸是同步 input()，两个子代理同时抢键盘会交错成灾难 |
| 工具实例浅拷贝防并发串扰 | 共享实例 | 顺序执行无并发；工具无 run 级可变状态 |
| contextvars 深度计数 | 无 | 见铁律一节 |
| workspace 用户模板 .md | 只内置两角色 | 缝：复用 skills/loader 的 parse_frontmatter |
| run 记账（conversation_store） | 无 | 我们没 run 表 |
| subagent_step 事件转播 | v1 静默 | 转播要动 loop→tool 的事件管道，留缝 |

## 踩到的两个真坑（测试抓的）

1. **None 顶掉默认参数**：`clear_session(sid, task.get("agent_id"))` 显式传了
   None，把 `agent_id=DEFAULT` 的默认值顶掉 → `Path / None` TypeError。
   教训：None 是值，不是"没传"。
2. **ERROR Reply 不是异常**：Agent.run 把循环异常包成 Reply（D004），
   runner 原以为子代理炸了会抛——结果全灭被误报成 completed。
   必须显式把 `ReplyType.ERROR` 翻译回 `failed`。
   这是"D004 失败变文本"和"编程式状态判断"的交界地带，两边都要长眼睛。

## 模板描述是路由不是说明

`description` 写给父模型看，回答"什么时候选我"而不是"我是什么"
（CowAgent templates.py 原话：This sentence is what it routes on）。
explore 强调"答案在某处需要找出来、且什么都不用改"——
父模型靠这句话决定派 explore 还是 general-purpose。
