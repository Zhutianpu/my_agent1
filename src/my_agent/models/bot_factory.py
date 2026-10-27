"""Bot 工厂：按配置造 bot。

SIMPLIFIED: CowAgent 支持 15 家厂商，这里只有 openai_compatible 一家。
以后要加厂商：写个子类，在下面的表里登记一行——别处一行不动。
"""

from ..common import const
from .bot import Bot
from .openai_compatible_bot import OpenAICompatibleBot

_BOT_TABLE = {
    const.OPENAI_COMPATIBLE: OpenAICompatibleBot,
}


def create_bot(bot_type: str = None) -> Bot:
    from ..config import conf

    btype = bot_type or conf().get("bot_type", const.OPENAI_COMPATIBLE)
    cls = _BOT_TABLE.get(btype)
    if cls is None:
        raise ValueError(f"未知 bot_type: {btype}（已登记的只有: {list(_BOT_TABLE)}）")
    return cls()
