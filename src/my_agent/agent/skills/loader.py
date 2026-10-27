"""SKILL.md 加载器（对齐 CowAgent skills/loader.py 的简化版）。

技能 = 一个目录 + 里面的 SKILL.md：

    skills/
      └── weekly-report/
            └── SKILL.md   ← frontmatter（name/description）+ 正文（操作手册）

frontmatter 是 markdown 开头的 --- 围栏 YAML：

    ---
    name: weekly-report
    description: 把一周的 git 提交和聊天记录整理成周报
    ---

SIMPLIFIED: CowAgent 递归扫描 + 文件签名缓存 + 一堆元数据（os/requires/
install/always）。我们：只扫一层（skills/*/SKILL.md）、每次现扫（文件小）、
frontmatter 只认 name 和 description 两个 key，手写解析不引 PyYAML。
"""

from dataclasses import dataclass
from pathlib import Path

from ...common.log import logger


@dataclass
class Skill:
    """一份技能说明书（对齐 CowAgent types.Skill 的精简字段）。"""
    name: str         # 技能名（frontmatter 的 name，缺省用目录名）
    description: str  # 什么时候用它（两段式的"第一段"，进 prompt 的就它）
    file_path: str    # SKILL.md 绝对路径（模型用 read_file 读正文）
    content: str      # 正文全文（不进 prompt，manager 留档备查）


def parse_frontmatter(text: str) -> dict:
    """解析 --- 围栏里的 key: value（只支持字符串值，够用）。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta = {}
    for line in text[3:end].strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def load_skills(skills_dir) -> list:
    """扫 skills_dir 下一层子目录里的 SKILL.md。坏文件跳过记日志，不炸装配。"""
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return []
    skills = []
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if not child.is_dir() or not skill_md.exists():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
            meta = parse_frontmatter(content)
            skills.append(Skill(
                name=meta.get("name", child.name),
                description=meta.get("description", ""),
                file_path=str(skill_md),
                content=content,
            ))
        except Exception:
            logger.exception(f"[Skills] 加载失败: {skill_md}")
    logger.debug(f"[Skills] 扫描 {skills_dir}: {len(skills)} 个技能")
    return skills
