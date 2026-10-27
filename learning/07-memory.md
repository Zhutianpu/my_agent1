# 阶段 7 笔记：记忆三条线

> 对照 CowAgent `agent/memory/`（7586 行）→ my-agent 三个文件约 400 行。

## CowAgent 的精髓（照搬的）

1. **记忆是两层蒸馏流水线**：原始对话 →（裁剪即蒸馏）→ 日记 memory/YYYY-MM-DD.md
   →（dream）→ 核心记忆 MEMORY.md。关键洞察：**裁剪不是丢弃，是蒸馏的触发点**——
   discard_exceeding 的返回值从"垃圾"变成"原料"。
2. **记忆必须可检索**：光写进文件没用，模型看不到。memory_search 工具让模型
   主动查（对齐 tool 契约：检索器 bind 进工具，工具本体不认识 workspace）。
3. **向量缺席时降级关键词**：CowAgent 自己就做了这个降级档——我们直接只实现
   降级档，search 接口不变，7d 加向量时上层无感。

## 砍掉的（# SIMPLIFIED）

- SQLite conversation_store（3161 行）→ jsonl 整写（肉眼可查，单用户够用）
- 内容哈希去重三件套 → 裁剪天然只裁一次，不会重复蒸馏
- 后台线程蒸馏 → 同步（回复已流式出去，用户感知不到；一轮最多裁一次）
- deep_dream 定时器 → #dream 手动命令
- 时间衰减 / rerank / hit_boost → 关键词打分先跑起来

## 真机/测试抓到的坑

- **env 配置覆盖全是字符串**：`CONVERSATION_MAX_MESSAGES=8` 一进 conf().get 就是
  str，跟 int 比较直接 TypeError。教训：所有数值配置 get 后必须 int()。
- **测试与持久化的冲突**：jsonl 落盘一开，上一次 pytest 的会话文件会在下次
  build_session 复活旧消息污染断言。解法：conftest 全局关 persist，
  要测持久化的测试自己开。这是"全局单例 + 文件副作用"的经典测试税。
- **裁剪时序**：第 N 轮的回复要第 N+1 轮（用户消息入列后）才被裁——
  集成测试里预算=4 时第三轮才触发首次蒸馏。
