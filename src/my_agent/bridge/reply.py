"""Reply：回复的"快递包裹"。

SIMPLIFIED: CowAgent 有 13 种 ReplyType（语音/名片/小程序…），砍到 TEXT + ERROR。
"""

from enum import Enum


class ReplyType(Enum):
    TEXT = 1
    ERROR = 10

    def __str__(self):
        return self.name


class Reply:
    def __init__(self, type: ReplyType = None, content=None):
        self.type = type
        self.content = content

    def __str__(self):
        return f"Reply(type={self.type}, content={self.content})"
