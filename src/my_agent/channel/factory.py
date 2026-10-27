"""Channel 工厂：按配置决定起哪个 channel（对齐 CowAgent channel_factory）。

SIMPLIFIED: CowAgent 的工厂支持多实例、凭据覆盖、队友派单（107 行 × 13 种
channel）。这里单实例两选一：terminal / web。多实例是 P2 以后的事。
"""

from ..config import conf
from .channel import Channel


def create_channel() -> Channel:
    channel_type = conf().get("channel", "terminal")
    if channel_type == "web":
        from .web.web_channel import WebChannel
        return WebChannel()
    from .terminal import TerminalChannel
    return TerminalChannel()
