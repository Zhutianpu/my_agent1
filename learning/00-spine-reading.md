# 00 · 脊柱精读（阶段 0 学习笔记）

> 读法：每个文件走"读→画契约→对照"三步。本笔记记录五份契约 + 六条原则。
> 读的文件：bridge.py / bot.py / session_manager.py / context.py / reply.py /
> terminal_channel.py / agent_initializer.initialize_agent / agent_stream.run_stream

## 一张总图纸

```
用户在终端敲字
  ↓
channel/terminal   翻译官：键盘输入 → Context；Reply → 屏幕显示（双向，不生产内容）
  ↓ produce(context)（kwargs 口袋里塞着 session_id 和 on_event 回调）
bridge/bridge.py   路由器：查表(chat→谁) + 懒加载缓存 bot + 转交
  ↓                    契约：query+Context 进来，Reply 出去；
  ↓                    自己不生成文本、不存历史、不认识任何厂商
models/bot         生成器：reply(query, context) -> Reply，一个接口覆盖所有厂商
  ↑                    厂商差异全部推给子类吸收，基类故意是空的
session/memory 层  历史的家：比 bot 长寿，所以历史住这里不住 bot 里
```

## 五份契约（脱口而出版）

1. **Bridge**：query+Context → Reply。三不：不生成文本、不存历史、不识厂商。
2. **Bot**：`reply(query, context) -> Reply`。无状态生成器，给料做菜，不留剩饭。
3. **Session/SessionManager**：一个 Session 是一段对话的本子（messages+system_prompt）；
   Manager 是按 session_id 存本子的柜子（get-or-create，可过期）。
4. **Context/Reply**：信封。type + content + kwargs 口袋。
   口袋 = 免检通道：任何层能塞元数据，信封类本身永不用改（开闭原则）。
5. **Agent 装配（initialize_agent）**：备料(记忆/工具/技能) → 编译 system prompt →
   总装 Agent → 恢复历史。顺序是硬约束：prompt 是用零件编译出来的。

## 心脏：工具循环只有 6 步

```
1. 用户消息 append
2. 裁剪上下文（循环外，只做一次！）
3. while turn < max_turns
4.   调 LLM → 文本 + tool_calls
5.   无 tool_calls → 返回，收工
6.   有 → 执行工具、回填结果、回到 3
```

CowAgent 的 agent_stream.py 有 2962 行——骨架和我一样，其余全是护甲。
护甲菜单：空响应重试✅、turn 上限✅、流式+事件✅、token 记账✅、
取消🟡、模型 fallback🟡、steering❌、MCP 动态检索❌。

## 六条原则（这次读代码真正的收获）

1. **下层不认识上层**：import 方向即依赖方向（bridge→models，反向没有）。
2. **状态存在最长寿的层**：对话比 bot 长寿，所以历史归 session/memory 层。
   反例：CowAgent 简单模式每个 bot 各抱一个柜子 → 换模型历史清零。
3. **system prompt 是编译产物，不是源码**：源码是注册表/目录/记忆库，
   prompt 是构建输出。装新工具不该改 prompt 文本。
4. **临时的归临时，持久的归持久**：注入的假消息用完要 pop，
   不能污染落盘的对话记录。
5. **裁剪在循环外做一次**：工具调用是订单+回执成对，循环中途裁剪
   会留下孤儿，模型格式报错 → 死循环。
6. **可变默认参数是坑**：`kwargs=dict()` 让所有实例共享一本字典
   （context.py 第 30 行的真实事故报告）。

## 我为 my-agent 拍下的边界决策

- bot 无状态；历史存在独立的 session 层（全局 SessionManager），换模型不丢
- Context/Reply 砍到 TEXT/ERROR 两种类型，kwargs 口袋原样保留
- channel 只留 terminal（双向翻译 + on_event 实况转播）
- 多 agent 确认要（P2），核心链留四条缝：(agent_id, session_id) 做存储 key、
  工作区按 agent 分目录、initializer 签名留 agent_id、ToolManager 支持白名单
