# 阶段 8 笔记：skills 两段式加载

> 对照 CowAgent `agent/skills/`（2519 行）→ my-agent 两个文件约 120 行。

## 核心设计：两段式加载

技能系统的本质矛盾：**技能想无限多，prompt 装不下**。解法：

```
第一段（装配时）：name + description + 路径 → 进 system prompt（每个技能几十字）
第二段（运行时）：模型自己判断描述匹配 → read_file 读 SKILL.md 正文 → 照做
```

所以 prompt 里的"使用纪律"不是废话，是机制的另一半：
"技能不是工具，不能直接调用；唯一用法是 read_file 读 SKILL.md 后照做；
一次只读一个"——不写死这句，模型会对着描述瞎猜正文。

## SKILL.md 契约

```
skills/<技能名>/SKILL.md
---
name: xxx
description: 什么时候用它（模型匹配的唯一依据，写好它是技能生效的关键）
---
正文：操作手册（流程/格式/要求）
```

加技能 = 扔目录 + #reset（重新装配重编 prompt）。零代码。

## 砍掉的（# SIMPLIFIED）

- 递归扫描 + 文件签名缓存 → 只扫一层，每次现扫
- enable/disable 配置持久化 → 全启用，不想要就删目录
- os/requires/install 依赖元数据 → 不装依赖的技能先不要这些
- 跨 agent 共享技能目录 → 每 agent 一份（P2 时再议共享）

## 边界自查

- builder 又一段"存在即编译"兑现：技能段的开关是 `skill_manager.build_skills_prompt()`
  返回非空——没技能时整段消失，prompt 不为空技能浪费一个字
- 测试守住的真契约：`正文不进 prompt`（断言"先问用户本周干了什么" not in prompt）
