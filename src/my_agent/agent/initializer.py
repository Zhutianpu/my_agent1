"""装配间（对齐 CowAgent bridge/agent_initializer.py 的极简版）。

一条流水线：备料 → 编译 → 总装。
  备料：ensure_workspace 造家 → load_context_files 读家 → runtime_info 收集元信息
  编译：build_system_prompt（纯函数，原料进字符串出）
  总装：Agent(bot, system_prompt)

P2 的缝：agent_id 参数决定用 workspaces/<agent_id>/ 哪个家。
多 agent 时每个 agent 装配一次，各住各的家、各持各的 prompt。

SIMPLIFIED: CowAgent 的装配间还管记忆系统、技能、scheduler、历史恢复
（它的历史在独立 memory 层）。我们的历史在 SESSIONS（agent.run 时挂上），
记忆/技能到阶段 7/8 再进这条流水线——位置已在下面标出。
"""

from datetime import datetime
from pathlib import Path

from ..common import const
from ..common.log import logger
from ..config import ROOT, conf
from .prompt import build_system_prompt, ensure_workspace, load_context_files
from .protocol.agent import Agent
from .tools import TOOLS


def workspace_dir_for(agent_id: str) -> Path:
    """agent 的家的位置。P2 落地：workspaces/<agent_id>/ 分目录。"""
    return ROOT / "workspaces" / agent_id


def initialize_agent(bot, agent_id: str = None, workspace_dir=None) -> Agent:
    """装配一个 agent。workspace_dir 参数是测试缝（真机走默认 workspaces/）。"""
    agent_id = agent_id or const.DEFAULT_AGENT_ID
    ws = Path(workspace_dir) if workspace_dir else workspace_dir_for(agent_id)

    # --- 备料 ---
    ensure_workspace(ws)
    context_files = load_context_files(ws)
    runtime_info = {
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": conf().get("model", ""),
        "workspace_dir": str(ws),
        "cwd": str(ROOT),  # 工具的 cwd ≠ agent 的家——真机教训：不说清楚它找不到 PLAN.md
        "agent_id": agent_id,
    }
    # 阶段 7：memory_manager = setup_memory(ws)
    # 阶段 8：skill_manager = load_skills(ws)

    # --- 编译 ---
    system_prompt = build_system_prompt(
        tools=TOOLS.schemas(),
        context_files=context_files,
        runtime_info=runtime_info,
        identity_fallback=conf().get("character_desc", ""),
    )
    logger.info(f"[Initializer] agent={agent_id} prompt 编译完成（{len(system_prompt)} 字符，"
                f"{len(context_files)} 个上下文文件）")

    # --- 总装 ---
    return Agent(bot=bot, system_prompt=system_prompt)
