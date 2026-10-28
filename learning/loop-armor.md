# 循环护甲二期笔记：空响应重试 / 取消 / 模型 fallback

> 对齐 CowAgent `agent_stream.py` 1027~1076（空响应重试）+ `cancel.py`（取消的完整性要求）。
> 模型 fallback 是我们自己的设计——CowAgent 的 "fallback" 指的是上下文窗口档位，不是换模型。

## 1. 空响应重试：用完 pop 的临时工

症状：工具跑完了，模型却一言不发（content 空、tool_calls 也没有）。
这在"模型觉得任务已完成"时真实发生。

CowAgent 的解法（照搬）：
- **turn > 1**（跑过工具）→ 注入一条 user 消息"请向用户说明刚才工具执行的结果
  或回答用户的问题"，再问一次；**记住注入位置，用完 pop**——催促是临时工，
  不能进持久历史，否则下次对话模型会看到一条用户没说过的怪话
- **turn == 1**（首轮就空）→ 不催促，直接兜底文案
- 催促后仍空 → 兜底文案："抱歉，我暂时无法生成回复……"
- 催促后反而给了 tool_calls → **不 break**，落回工具路径（模型只是换了个方式继续干活）

砍掉的：allow_empty_response（那是给定时任务"允许沉默"用的，我们没有定时任务）。

## 2. 取消：中断可以，配对不能破

KeyboardInterrupt 是 BaseException 不是 Exception——`except Exception` 兜不住它，
这正是之前 Ctrl+C 会直接杀穿整个 app 的原因。

接住它之后的**真正难点是消息完整性**：assistant 消息带了 3 个 tool_calls，
执行到第 2 个被中断——如果只回填了 1 个 tool result，下一轮 API 调用直接报错
（每个 tool_call 必须有配对 result，这是硬协议）。所以中断收尾时，
**剩余未执行的 tool_call 全部补一条"（执行被用户中断）"的 tool result**，
再补一条 assistant 中断说明，历史保持一问一答，app 不死。

两层防线：循环内（chat/工具执行）loop.py 自己接住正常返回；
循环外（罕见，如蒸馏时）agent.run 兜住，存历史、返回中断 Reply。
终端 UX 因此变成：跑的时候 Ctrl+C = 中止这轮，提示符下 Ctrl+C = 退出。

SIMPLIFIED：CowAgent 的 cancel.py 是给 web 用的请求级 CancelTokenRegistry
（按钮取消、跨请求注销），我们只要键盘中断这一档。web 取消按钮要做时，
把 KeyboardInterrupt 换成轮询 cancel_event 即可——缝在 chat()/工具循环两处检查点。

## 3. 模型 fallback（自有设计）

config.json 加 `"fallback_model": "别的模型名"`（默认空=关闭）。
bot.chat 抛异常 → 同一 run 内粘性切换：造一个只换 model 名的新 bot
（key/base 不变），重试一次，后续 turn 都用它。备用也挂 → 异常上去走原 error 路径。

配套改动：`create_bot(model=...)` / `OpenAICompatibleBot(model=...)` 支持覆盖，
一行的事——这就是"换 LLM 只动 models/"的边界红利。

## 顺手修的测试污染

test_stage10 的工厂测试假设"默认 terminal"，结果真机 config.json 改成 web 后就红了。
教训和 CONVERSATION_MAX_MESSAGES 那次同族：**测试不能依赖真机配置**，
用 env 覆盖（优先级高于 config.json）把配置钉死。

## 验收心法

- 空响应重试：难人为触发，靠测试剧本担保（4 个用例覆盖全部分支）
- 取消：真机让它跑长任务（写长文/连环工具），中途 Ctrl+C，
  预期：出中断提示、回到提示符、**下一句还能正常聊**（历史没破）
- fallback：config.json 填个 fallback_model，把 model 故意改错重启，
  预期：第一轮出"切换备用模型"提示，然后正常回答

---

# 三期：上下文溢出恢复（2026-10-28）

> 对齐 CowAgent `agent_stream.py` 的被动道（`_overflow_input_budget` :2605 /
> `_smart_compact_to_budget` :2632 / 只重试一次 :1874）+ 主动道 `_trim_messages` :2785。
> 核心思想一句话：**平时靠估算主动裁，撞墙了从报错里抠真实数字，照着真实数字压缩重试。**

## 两道防线的分工

| | 主动道 | 被动道 |
|---|---|---|
| 触发 | 每次 run，估算超预算就裁 | LLM 调用抛 overflow 异常才启动 |
| 预算 | 窗口×0.8 − system（20% 输出预留） | 报错里抠出的真实数字 ×0.9 |
| 落点 | `discard_over_tokens` | 同一个 `discard_over_tokens` |

预算公式两处都减 system 单独估算；20% 输出预留**故意不用模型 max output**
（CowAgent 注释：DeepSeek 384K 输出上限会把压缩线拖到 62%；80% 是
Claude Code/Cursor/Cline 的惯例）。

## 关键设计点

1. **报错即数据源**：provider 的 400 原文白送真实窗口/completion/消息占用三个数。
   抠不到才回退配置估算。CowAgent 记过 LinkAI 的教训：蒙着砍一半会
   "压→还超→再压→再撞"锤死循环——所以照真实数字压，且**只重试一次**
   （`_overflow_stage` 计数器）。
2. **溢出不走模型 fallback**：同样的上下文换备用模型照样撞。loop 里判型
   抢在 fallback 之前抛 `ContextOverflowError`。
3. **压缩两步走**（`discard_over_tokens`）：先截断老轮次工具结果
   （写入上限 6000 字符对历史太松，收到 500；最后一轮不动），不够再按
   user 边界整轮丢。最后一轮永远保留——用户刚说的话不能丢。
4. **裁剪之前先保命**：裁掉的照样走"蒸馏→摘要注回"管线（`flush_memory`
   reason="overflow" 同款），压缩≠遗忘。
5. **压不动就认**：清内存（`session.reset()` 重建 system 头）不落盘，
   磁盘历史保住，告诉用户"请重新描述需求"。
   SIMPLIFIED：jsonl 整写意味着下次成功保存仍会覆盖磁盘；CowAgent 的
   SQLite 才谈得上真正长期保留。

## 顺手修的关联 bug

空响应重试的催促注入改成 `finally pop`——原来异常路径（比如催促那次 chat
恰好撞墙）会把"请向用户说明……"这条假 user 消息留在持久历史里。

## 测试（15 个，125 全绿）

估算比例（CJK×1.5/ASCII÷4）、system 不计入、tool_calls 结构开销、
判型真假例（含 OpenAI 下划线错误码超集）、报错抠预算/回退、80% 主动预算、
边界安全裁剪、截断优先于丢弃、单轮巨物报 not-fits、agent 级恢复/蒸馏/双击道歉、
溢出不触发 fallback、催促注入 finally pop。

## 验收心法

- 主动道：config.json 把 `model_context_window` 塞到 2000，正常聊两句——
  预期每轮都触发 token 裁剪，蒸馏文件有新条目，对话不断片
- 被动道：真 overflow 要烧 64K+ token，不真机硬测；离线测试用 provider
  真实报错样本担保（ CowAgent 注释里抄的那行）
