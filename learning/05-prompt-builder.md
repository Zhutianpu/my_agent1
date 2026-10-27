# 阶段 5 笔记：prompt 是编译产物

> 对照 CowAgent `agent/prompt/`（builder.py 1117 行 + workspace.py 758 行）→ my-agent 两个文件共约 200 行。

## 三份契约

1. **workspace.py = agent 的家**
   - `ensure_workspace` 幂等造家：缺的模板补上，改过的绝不覆盖
   - `load_context_files` 读家：空文件、纯占位符模板跳过（没填过的不进 prompt）
2. **builder.py = 编译器**：纯函数，原料进字符串出
   - 核心设计：**分段 + 存在即编译**（`if tools: sections += ...`）
   - 段开关 = 扩展缝：阶段 7 记忆、阶段 8 技能接入时 builder 一行不改
3. **initializer.py = 装配间**：备料 → 编译 → 总装
   - Bridge 从此不认识 prompt 怎么来的（Bridge 只剩路由本职）

## 对齐 CowAgent 时抄到的细节

- **MEMORY.md 截断保留尾部**：新记忆追加在末尾，截头不截尾（200 行 / 25KB 先到先截）
- **占位符检测**：`*(待填写)` 标记 + 真实行数 ≤3 才算"没填过"。
  注意 CowAgent 的 USER.md 模板其实会被加载（行数多）——这是有意的：
  让模型看到表格结构才知道要填什么。我们照搬了这个行为。
- **段序有讲究**：工具最前（最重要），运行时信息最后（元信息）；
  上下文文件（身份）在中间偏后，离用户消息近
- **prompt 每轮刷新**：session.messages[0] 是可替换的编译产物，不是刻死的基石。
  #reset 连 agent 一起丢 → 重新装配 → 改过的 AGENT.md 立即生效

## 砍掉的（# SIMPLIFIED）

- RULE.md 并进 AGENT.md（家规不值得单文件）
- BOOTSTRAP.md 首次引导（填完即删的引导流程，复杂度不值）
- knowledge/ 目录、双语模板、i18n
- 技能段 / 记忆段 / 权限段 / 团队段 —— 全是阶段 7/8/6/P2 的坑位

## 边界自查

- 换 LLM → 只动 models/ ✅（prompt 编译与厂商无关）
- 加 prompt 段 → builder 加一个 `_xxx_section` + 一个 if ✅
- 改身份 → 改 workspaces/default/AGENT.md + #reset，不动代码 ✅
