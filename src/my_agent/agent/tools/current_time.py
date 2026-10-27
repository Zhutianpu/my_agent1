"""current_time：报当前时间。模型没有时钟，想要"现在几点"只能靠它。"""

from datetime import datetime

from .base_tool import BaseTool, ToolResult


class CurrentTimeTool(BaseTool):
    name = "current_time"
    description = "获取当前的日期和时间。"
    params = {"type": "object", "properties": {}}

    def execute(self) -> ToolResult:
        now = datetime.now()
        # 真机抓过的 bug：曾写成 f"星期{'一二三四五六日'}[now.weekday()]"，
        # 右括号位置错了，[now.weekday()] 落在大括号外变成字面文本发给了模型。
        weekday = "一二三四五六日"[now.weekday()]
        return ToolResult.success(now.strftime(f"%Y-%m-%d %H:%M:%S（星期{weekday}）"))
