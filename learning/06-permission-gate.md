# 阶段 6 笔记：权限闸

> 对照 CowAgent `agent/permission/policy.py`（982 行静态分析器）→ my-agent 交互闸约 80 行。

## 两种授权哲学

| | CowAgent | my-agent |
|---|---|---|
| 授权方式 | 切模式（read-only / workspace-write / full-access） | 逐次问 y/a/n |
| 风险判断 | **静态分析参数**：bash 命令分段、sed -i、git 子命令、重定向目标全解析 | **工具自报**：BaseTool.risk 类属性 |
| 记住授权 | 模式持久化在配置 | remembered 集合（进程内） |
| 拒绝处理 | 拒绝文本回填 + "请切换权限模式"提示 | 拒绝文本回填 + "换思路/征得同意"提示 |

CowAgent 的做法适合常驻服务（IM channel 里没法弹 input）；我们的终端 REPL
逐次问更直观，也是 offer-coach 验证过的经验。

## 三条不变量（以后 Review 盯这些）

1. **闸在必经之路上**：挂在 ToolManager.execute，loop.py 不认识权限的存在
2. **拒绝 = 错误文本**：模型读得懂"用户拒绝了"，会自己换方案（集成测试验证：
   被拒后模型第二轮改用嘴回答）——这是 D004 的延伸
3. **闸永不抛异常**：handler 炸了 fail-open + 日志，对话不能死

## 缝（以后兑现）

- `GATE.confirm_handler` 由 channel 启动时注入——阶段 10 web console 换异步确认只动这里
- remembered 按工具名记；要更细（按路径/命令头）时改 `GATE._check` 的 key 一处
- headless（无 handler）= 放行：这是测试保持绿色的前提，也意味着脚本化调用
  时闸是开着的——部署成服务时要把默认改成拒绝
