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
        self._agents = {}  # agent_id -> 装配好的 Agent（P2 的缝：多 agent 各装配各的）

    def get_bot(self, typename="chat"):
        """懒加载 + 缓存：第一次用到才创建，之后复用。"""
        if self.bots.get(typename) is None:
            logger.info(f"[Bridge] 创建 bot: {self.btype[typename]} (for {typename})")
            self.bots[typename] = create_bot(self.btype[typename])
        return self.bots[typename]

    def get_agent(self, agent_id=None):
        """agent 模式的入口（阶段 5：经装配间编译 prompt；局部 import 破环）。"""
        agent_id = agent_id or const.DEFAULT_AGENT_ID
        if agent_id not in self._agents:
            from ..agent.initializer import initialize_agent
            self._agents[agent_id] = initialize_agent(bot=self.get_bot("chat"), agent_id=agent_id)
        return self._agents[agent_id]

    def fetch_agent_reply(self, query: str, context: Context = None) -> Reply:
        agent_id = context.get("agent_id") if context else None
        return self.get_agent(agent_id).run(query, context)

    def reset_agent(self, agent_id=None):
        """丢弃装配好的 agent，下次用到时重新装配（重编 prompt）。
        #reset 时调用：改了 AGENT.md 想立即生效就靠它。"""
        if agent_id:
            self._agents.pop(agent_id, None)
        else:
            self._agents.clear()

    def reset_bot(self):
        """配置变了就重置路由（换模型后调用）。"""
        self.__init__()
