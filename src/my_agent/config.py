"""配置系统：config.json + .env。

SIMPLIFIED: CowAgent 的 config.py 有 1029 行（多渠道热更新、web 控制台写回、
深合并默认值等）。这里只保留最小闭环：启动时加载一次，conf().get() 读取。
密钥优先读环境变量（.env），避免明文进 config.json。
"""

import json
import threading
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # src/my_agent/config.py -> my-agent/
load_dotenv(ROOT / ".env")


class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}
        self.reload()

    def reload(self):
        path = ROOT / "config.json"
        if not path.exists():
            path = ROOT / "config-template.json"
        with self._lock:
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key, default=None):
        import os
        env_val = os.environ.get(key.upper())
        if env_val:
            return env_val
        return self._data.get(key, default)


_config = None


def conf() -> Config:
    """全局唯一配置入口（单例）。"""
    global _config
    if _config is None:
        _config = Config()
    return _config
