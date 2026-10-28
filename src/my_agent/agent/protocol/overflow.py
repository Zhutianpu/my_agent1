"""上下文溢出：判型 + 预算抠取（护甲三期，对齐 CowAgent agent_stream.py）。

核心思想：平时靠估算主动裁，撞墙了从报错里抠真实数字，照着真实数字
压缩重试——报错本身就是数据源：

  "maximum context length is 1048576 tokens. However, you requested
   1276733 tokens (892733 in the messages, 384000 in the completion)"

这行白送三个真实数字：真实窗口、消息占用、completion 占用。

SIMPLIFIED：
- 窗口回退只有一级（config "model_context_window"，默认 128000）；
  CowAgent 是三级（用户配置 → 内置模型族表 → 默认 128K）
- 无 [context_overflow] 内部跨层标记——我们直接抛 ContextOverflowError
- token 估算不在这里：它是 session 自己的计量（models/session_manager.py），
  本模块只管"这是不是溢出"和"该照多少裁"
"""

import re

from ...config import conf

# 对齐 CowAgent _CONTEXT_OVERFLOW_MARKERS，外加一个超集：
# "context_length_exceeded" 是 OpenAI 系的错误码（下划线形）。CowAgent 靠
# 报错消息体里的 "maximum context length" 命中；错误码单独出现时也值得接住。
_MARKERS = (
    "context length exceeded", "context_length_exceeded",
    "maximum context length", "prompt is too long",
    "context overflow", "context window", "exceeds model context",
    "request_too_large", "request exceeds the maximum size",
    "too many tokens", "input is too long", "tokens exceed",
)

_RE_LIMIT = re.compile(r"maximum context length is\s+(\d+)\s*tokens", re.I)
_RE_COMPLETION = re.compile(r"(\d+)\s+in the completion", re.I)

_FLOOR = 2000  # 预算下限：再低连一轮对话都放不下，压了也白压


class ContextOverflowError(Exception):
    """上下文溢出专用异常。和普通模型错误分开：换备用模型救不了溢出
    （同样的上下文换谁照样撞），必须先压缩再重试——所以它在 loop 里
    抢在 fallback 之前抛出。"""


def is_context_overflow(error_str: str) -> bool:
    s = (error_str or "").lower()
    return any(m in s for m in _MARKERS)


def _window() -> int:
    return int(conf().get("model_context_window", 128000))


def proactive_budget(system_tokens: int) -> int:
    """主动道预算（对齐 _trim_messages）：窗口 − 20% 输出预留 − system。

    输出预留固定 20%、故意不用模型的 max output——CowAgent 注释原话：
    DeepSeek 384K 的输出上限会把压缩线拖到 62%。压缩线压在窗口 80%
    是 Claude Code / Cursor / Cline 的惯例。
    """
    return max(_FLOOR, int(_window() * 0.8) - system_tokens)


def overflow_budget(error_str: str, system_tokens: int) -> int:
    """被动道预算（对齐 _overflow_input_budget）：从报错抠真实数字，
    抠不到回退配置估算。×0.9 吸收"我的估算 vs provider 真实分词器"的误差。
    """
    m = _RE_LIMIT.search(error_str or "")
    window = int(m.group(1)) if m else _window()
    m = _RE_COMPLETION.search(error_str or "")
    completion = int(m.group(1)) if m else int(window * 0.2)
    return max(_FLOOR, int((window - completion - system_tokens) * 0.9))
