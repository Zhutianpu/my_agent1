"""日志：同时写控制台和 run.log。"""

import logging
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[3]  # src/my_agent/common/log.py -> my-agent/


def _build_logger():
    logger = logging.getLogger("my_agent")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


logger = _build_logger()
