"""Channel 基类：接入层的契约。

channel 是双向翻译官：
  进口（startup）：用户输入 → Context → produce()
  出口（send）：    Reply → 人能看到的东西
它不生产任何内容。

produce 的 SIMPLIFIED：CowAgent 用生产者-消费者队列 + 后台线程池处理消息，
这里同步直调——terminal 单用户场景下队列是过度设计。
"""

from ..bridge.bridge import Bridge
from ..bridge.context import Context
from ..bridge.reply import Reply


class Channel:
    def startup(self):
        raise NotImplementedError

    def send(self, reply: Reply, context: Context):
        raise NotImplementedError


class ChatChannel(Channel):
    def produce(self, context: Context):
        reply = Bridge().fetch_agent_reply(context.content, context)
        self.send(reply, context)
