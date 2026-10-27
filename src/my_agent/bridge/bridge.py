"""Bridge：路由中枢。

契约：query+Context 进来，Reply 出去。
三不：不生成文本、不存历史、不认识任何厂商。

SIMPLIFIED: CowAgent 的 Bridge 还要路由 voice/translate/多家模型猜测逻辑，
这里只剩 chat 一路 + 懒加载缓存（bot 对象很贵，第一次用到才造，造完复用）。
"""

from ..common import const
from ..common.log import logger
from ..common.singleton import singleton
from ..config import conf
from ..models.bot_factory import create_bot
from .context import Context
from .reply import Reply


@singleton
class Bridge:
    def __init__(self):
        # 路由表：什么类型的请求找哪家厂商。配置直接指定，不做模型名猜测。
        self.btype = {"chat": conf().get("bot_type", const.OPENAI_COMPATIBLE)}
        self.bots = {}
        self._agent = None

    def get_bot(self, typename="chat"):
        """懒加载 + 缓存：第一次用到才创建，之后复用。"""
        if self.bots.get(typename) is None:
            logger.info(f"[Bridge] 创建 bot: {self.btype[typename]} (for {typename})")
            self.bots[typename] = create_bot(self.btype[typename])
        return self.bots[typename]

    def get_agent(self):
        """agent 模式的入口（局部 import 破环：bridge ↔ agent.protocol）。"""
        if self._agent is None:
            from ..agent.protocol.agent import Agent
            self._agent = Agent(bot=self.get_bot("chat"))
        return self._agent

    def fetch_agent_reply(self, query: str, context: Context = None) -> Reply:
        return self.get_agent().run(query, context)

    def reset_bot(self):
        """配置变了就重置路由（换模型后调用）。"""
        self.__init__()
