"""技能系统（对齐 CowAgent agent/skills 的简化版）。

  loader.py  —— 扫 skills/<技能名>/SKILL.md，解析 frontmatter
  manager.py —— 出"描述清单"给 prompt 编译器（两段式加载的第一段）
"""

from .loader import Skill, load_skills
from .manager import SkillManager

__all__ = ["Skill", "load_skills", "SkillManager"]
