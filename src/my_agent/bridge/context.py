"""Context：消息的"信封 + 面单 + 口袋"。

契约：type（什么种类）+ content（内容本体）+ kwargs（口袋，元数据免检通道）。
SIMPLIFIED: CowAgent 有 12 种 ContextType（多为 IM 特有：拍一拍/加好友/群聊），
这里砍到 TEXT，IMAGE 留作以后。
"""

from enum import Enum


class ContextType(Enum):
    TEXT = 1
    IMAGE = 3

    def __str__(self):
        return self.name


class Context:
    def __init__(self, type: ContextType = None, content=None, kwargs=None):
        self.type = type
        self.content = content
        # 别写 kwargs=dict()：默认值只在函数定义时评估一次，
        # 所有实例会共享同一个 dict（CowAgent context.py 第30行的真实事故）。
        self.kwargs = {} if kwargs is None else kwargs

    def __contains__(self, key):
        if key == "type":
            return self.type is not None
        if key == "content":
            return self.content is not None
        return key in self.kwargs

    def __getitem__(self, key):
        if key == "type":
            return self.type
        if key == "content":
            return self.content
        return self.kwargs[key]

    def __setitem__(self, key, value):
        if key == "type":
            self.type = value
        elif key == "content":
            self.content = value
        else:
            self.kwargs[key] = value

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __str__(self):
        return f"Context(type={self.type}, content={self.content}, kwargs={self.kwargs})"
