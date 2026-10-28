# P2 多 agent：花名册 + 派单 + 信箱

> 对齐 CowAgent `agent/registry.py` + `agent/routing.py` +
> `agent/multiagent/transport.py` + `agent/tools/agent_delegate/`（719 行）。
> 一句话：**多 agent = N 次单 agent 装配 + 三本账**。
> 四条预留缝全部兑现：(agent_id,session_id) 键 / workspaces 分目录 /
> initializer 签名 / 工具白名单。

## 三本账

| 账 | CowAgent | 我们 | 文件 |
|---|---|---|---|
| 花名册 | registry.py：AgentProfile 一堆字段 + 持久化 | id/name/description 三样，config.json "agents" 现读 | `agent/roster.py` |
| 派单 | agent_delegate.py 719 行：trace 元组 + max_depth=3 + 三 mode | 结构级防循环（白名单摘派单工具）+ 在跑栈防嵌套 | `tools/agent_delegate.py` |
| 信箱 | transport.py：跨进程 InvokeRequest 走 socket | 每 agent 一个 jsonl，上线 drain 进用户消息 | `agent/mailbox.py` |

## 关键设计决策

**1. 委托进对方的主会话，不是隔离会话。**
subagent 是雇工（用完即弃），delegate 是同事（记得住）。被派的活留在
对方的 ("builder","default") 会话里——`#use builder` 切过去问
"我刚才让你干了啥"它知道。这是和阶段 11 最本质的区别，一句话选型标准：
**要隔离用 subagent，要记忆用 delegate。**

**2. 循环防护：CowAgent 数深度，我们摘工具。**
CowAgent 的 delegation_trace 元组 + max_depth=3 是在"任何 agent 都能派单"
的前提下事后拦。我们沿用阶段 11 的招式：被派单者的工具集里**没有**
agent_delegate——A→B→A 在结构上不可能，深度计数成了多余。
但有一个洞摘工具堵不上：**派给自己**（default→default 两个 run 嵌套同一
session 对象，历史绞麻花）。补一个"在跑栈"（threading.local 的
(agent_id, session_id) 栈）：目标是栈里的人就拒。这就是 trace 的极简版。

**3. 在跑栈的副产品：自动署名。**
栈顶就是调用者。委托包装语"来自 agent「default」的委托"、留言的 from 字段
都不需要模型自报家门——harness 比模型更知道谁在说话。

**4. 信箱是"上线才签收"。**
send 只追加 jsonl，对方下次 run 时 drain 出来拼进本轮用户消息。
好处：零调度（不需要唤醒机制），坏处：对方不被叫醒就永远看不到——
所以工具 description 里写死分工："要结果用 delegate，知会用 message"。

## SIMPLIFIED 清单

- 砍 workspace/model/skills/knowledge 档案字段（约定 workspaces/<id>/）
- 砍 max_depth 配置、trace 参数、三 mode（CLEAR 有 #reset）
- 砍 socket 传输、并发派单、事件转播（看实况用 #use 切过去）
- 路由：CowAgent 的 channel 绑定 + 显式 agent_id 两路，我们只有终端 #use

## 测试（13 个，110 全绿）

花名册解析（含坏 id/冒充 default/重复）、动态说明书、未知 id、派单全链路
（包装+白名单+主会话留痕）、在跑栈拒绝、ERROR Reply 翻译、完整循环署名、
信箱收发/签收注入/自留言拒绝。

## 真机抓的 bug：subset 生成器耗尽（面试素材级）

**现象**：验收时 builder 写诗成功、写文件报"未知工具 write_file
（可用的只有: ['read_file']）"，default 只好替它落盘。

**根因**：`ToolManager.subset` 里 `{... if n in set(names)}`——`set(names)`
写在字典推导式的 if 子句里，**每次迭代重新求值**。delegate 传的 names 是
生成器（一次性）：第一次迭代消费完（read_file 通过），第二次起永远空集，
10 件工具裁到只剩 1 件。阶段 11 传 list 可重复消费，坑潜伏三个阶段没炸。

**为什么 109 测试全绿还漏网**：派单测试只断言 `"agent_delegate" not in
peer_tool_names`（反向：没有坏事），没断言 `write_file in ...`（正向：有好事）。
教训：**白名单类逻辑必须双向断言**——"坏人进不来"和"好人没误伤"各一条。

**修复**：`allowed = set(names)` 提升出推导式（一行）。补正向断言 +
生成器回归测试。

## 真机抓的 bug 2：测试吃掉真机信箱（污染家族第四员）

**现象**：修完 subset 后重验，builder 被派单唤醒时信箱文件消失了，
但会话里找不到【信箱】注入——留言凭空蒸发。

**根因**：我修完 subset 跑的那次 `pytest`（110 全绿）里，派单测试会
启动 agent_id=builder 的 peer Agent → `_run_inner` 无条件 drain 真机
`workspaces/builder/mailbox.jsonl`——用户在上一轮验收里留的真言被
测试读走删掉。Agent.run 新增了信箱这个全局触点，测试沙箱没跟上。

**修复**：conftest 加 `_isolated_mailbox` autouse 夹具，mailbox.ROOT
全局重定向到 tmp_path——和 SESSIONS.persist=False、GATE.reset 同级。
测试污染家族：jsonl 持久化 / 权限闸 handler / 真机 config / **真机信箱**。
家族共性：**每给 Agent.run 加一个全局副作用，conftest 就要多一道隔离**。

**戏剧性细节**：110 全绿的测试恰恰是肇事者——测试通过和测试肇事
可以同时成立，因为断言从没检查"我没碰不该碰的东西"。
