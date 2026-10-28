"""花名册：多 agent 的注册表（对齐 CowAgent registry.py 的极简版）。

CowAgent 的 AgentProfile 有 workspace/model/skills/knowledge 等一堆字段；
我们的"档案"只有三样：id / name / description。
description 是给其他 agent 看的——光知道名字只能喊人，
知道"他是干嘛的"才能决定这活该派给谁（CowAgent 原话的意思）。

SIMPLIFIED：workspace 不给配——约定 workspaces/<id>/（阶段 5 的缝）；
enabled/skills/knowledge 裁剪全砍。default agent 永远在册。
"""

import re
from dataclasses import dataclass

from ..common.log import logger
from ..config import conf

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    description: str = ""


def load_roster() -> dict:
    """config.json 的 "agents" 列表 + 永远在册的 default。

    每次现读（conf 已在内存里，开销为零）——改了配置下个动作就生效。
    坏条目跳过并告警，不拖垮花名册（CowAgent 同款宽容）。
    """
    roster = {"default": AgentProfile("default", "默认助手", "主人直接对话的 agent")}
    raw = conf().get("agents") or []
    if not isinstance(raw, list):
        logger.warning("[Roster] config 的 agents 必须是列表，忽略")
        return roster
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("id") or "").strip()
        if not _ID_RE.match(pid):
            logger.warning(f"[Roster] 非法 agent id: {pid!r}（字母数字开头，可含 - _）")
            continue
        if pid in roster:
            logger.warning(f"[Roster] 重复的 agent id: {pid}，跳过")
            continue
        roster[pid] = AgentProfile(
            id=pid,
            name=str(entry.get("name") or pid).strip(),
            description=str(entry.get("description") or "").strip(),
        )
    return roster
