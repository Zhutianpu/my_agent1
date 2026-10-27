"""权限闸：危险操作执行前的检查点（对齐 CowAgent agent/permission/policy.py 的简化版）。

契约照搬：check(...) -> Decision(allowed, reason)，拒绝时 reason 是回填给
模型的错误文本（模型读得懂，会换方案——D004 的延伸，同构 CowAgent 的
_permission_denial）。检查挂在 ToolManager.execute 这个必经之路上，
loop.py 一行不改。

SIMPLIFIED: CowAgent 是静态政策闸——三模式（read-only/workspace-write/
full-access）+ 982 行 bash 命令分段分析器（连 sed -i、git 子命令、重定向
目标都解析），用户靠切模式授权。我们走交互式：
  - 风险由工具自报（BaseTool.risk），不静态分析参数
  - 写类工具首次执行前问用户：y=允许一次 / a=此类都允许（记住）/ n=拒绝
  - remembered 集合只在进程内有效（CowAgent 的模式持久化在配置里）

confirm_handler 由 channel 在启动时注入（terminal 弹 input()）。
没注入 = headless/测试模式 = 放行 + 警告日志。阶段 10 web console 需要
换成异步确认——handler 注入点就是为那时留的缝。
"""

import json

from ...common.log import logger


class Decision:
    """一次权限检查的结果（对齐 CowAgent policy.Decision）。"""

    def __init__(self, allowed: bool, reason: str = ""):
        self.allowed = allowed
        self.reason = reason

    def __bool__(self):
        return self.allowed


ALLOW = Decision(True)

# 审计日志里参数预览的最大长度（write_file 的 content 可能很长）
_ARGS_PREVIEW_MAX = 200


class PermissionGate:
    def __init__(self):
        # channel 注入的询问器：fn(tool_name, args) -> "y" | "a" | "n"
        self.confirm_handler = None
        # 用户说过"此类都允许"的工具名（进程内有效）
        self.remembered = set()

    def reset(self):
        """测试/重启用：清空记忆和 handler。"""
        self.confirm_handler = None
        self.remembered.clear()

    def check(self, tool, args: dict) -> Decision:
        """必经之路上的检查。永不抛异常——闸坏了不能炸掉对话。"""
        try:
            return self._check(tool, args)
        except Exception as e:
            logger.exception("[Permission] 检查异常，放行")
            return ALLOW

    def _check(self, tool, args: dict) -> Decision:
        risk = getattr(tool, "risk", "read")
        if risk == "read":
            return ALLOW
        if tool.name in self.remembered:
            return ALLOW
        if self.confirm_handler is None:
            logger.warning(f"[Permission] 无确认渠道，放行 {tool.name}（headless 模式）")
            return ALLOW

        answer = self.confirm_handler(tool.name, args)
        preview = json.dumps(args, ensure_ascii=False)[:_ARGS_PREVIEW_MAX]
        if answer == "a":
            self.remembered.add(tool.name)
            logger.info(f"[Permission] {tool.name} {preview} -> 允许（此类都允许，已记住）")
            return ALLOW
        if answer == "y":
            logger.info(f"[Permission] {tool.name} {preview} -> 允许（一次）")
            return ALLOW
        logger.info(f"[Permission] {tool.name} {preview} -> 拒绝")
        return Decision(
            False,
            "用户拒绝了这次操作。请换个思路：改用只读方式完成，"
            "或向用户解释为什么需要这个操作、征得同意后再试。",
        )


GATE = PermissionGate()
