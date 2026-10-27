"""技能管理器（对齐 CowAgent skills/manager.py 的极简版）。

职责只有一个：出"描述清单"给 prompt 编译器。
两段式加载的分工：
  第一段（这里）：name + description + 路径 → 进 system prompt（几十个字的索引）
  第二段（模型自己）：描述匹配时才 read_file 读正文（操作手册不进 prompt）

SIMPLIFIED: CowAgent 还有启用/禁用配置持久化、可用性过滤、快照版本号。
我们的技能全启用、每次装配现扫——加技能 = 扔个目录进去 + #reset。
"""

from pathlib import Path

from .loader import load_skills


class SkillManager:
    def __init__(self, skills_dir):
        self.skills_dir = Path(skills_dir)
        self.skills = []

    def refresh(self):
        """重新扫描技能目录（装配时调一次）。"""
        self.skills = load_skills(self.skills_dir)
        return self

    def build_skills_prompt(self) -> str:
        """描述清单。没有技能时返回空串——builder 看到空串就不编技能段。"""
        if not self.skills:
            return ""
        lines = []
        for s in self.skills:
            desc = s.description or "（无描述）"
            lines.append(f"- **{s.name}**：{desc}\n  位置：{s.file_path}")
        return "\n".join(lines)

    def get(self, name: str):
        for s in self.skills:
            if s.name == name:
                return s
        return None
