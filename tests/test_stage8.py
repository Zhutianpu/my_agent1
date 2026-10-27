"""阶段 8 验收测试：skills 两段式加载。

验证的契约：loader 扫目录解析 frontmatter；manager 出描述清单；
builder 的技能段带"使用纪律"且只在有技能时编译；装配间把技能编进 prompt。
"""

from my_agent.agent.initializer import initialize_agent
from my_agent.agent.prompt import build_system_prompt, ensure_workspace
from my_agent.agent.skills import SkillManager, load_skills
from my_agent.agent.skills.loader import parse_frontmatter

_SKILL_MD = """---
name: weekly-report
description: 把一周的流水账整理成结构化周报
---

# 周报技能

1. 先问用户本周干了什么
2. 按【完成/进行中/下周计划】三段输出
"""


def _make_skills_dir(tmp_path):
    ws = ensure_workspace(tmp_path / "ws")
    skill_dir = ws / "skills" / "weekly-report"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    return ws


# ---------- loader ----------

def test_parse_frontmatter():
    meta = parse_frontmatter(_SKILL_MD)
    assert meta == {"name": "weekly-report", "description": "把一周的流水账整理成结构化周报"}
    assert parse_frontmatter("# 没有围栏") == {}
    assert parse_frontmatter("---\nname: x") == {}  # 没有收尾围栏


def test_load_skills(tmp_path):
    ws = _make_skills_dir(tmp_path)
    # 一个没 frontmatter 的（名字回退到目录名）+ 一个坏编码以外的正常文件
    plain = ws / "skills" / "plain"
    plain.mkdir()
    (plain / "SKILL.md").write_text("# 随便\n", encoding="utf-8")
    (ws / "skills" / "stray-file.txt").write_text("不是目录", encoding="utf-8")

    skills = load_skills(ws / "skills")
    by_name = {s.name: s for s in skills}
    assert by_name["weekly-report"].description == "把一周的流水账整理成结构化周报"
    assert by_name["plain"].description == ""  # 目录名兜底
    assert len(skills) == 2  # 散装文件不算技能
    assert (ws / "skills") .exists()  # ensure_workspace 造好了技能目录


def test_load_skills_missing_dir(tmp_path):
    assert load_skills(tmp_path / "不存在") == []


# ---------- manager + builder ----------

def test_manager_prompt_list(tmp_path):
    ws = _make_skills_dir(tmp_path)
    mgr = SkillManager(ws / "skills").refresh()
    prompt = mgr.build_skills_prompt()
    assert "weekly-report" in prompt and "整理成结构化周报" in prompt
    assert str(ws / "skills" / "weekly-report" / "SKILL.md") in prompt  # 路径给模型去读
    assert SkillManager(tmp_path / "空").refresh().build_skills_prompt() == ""


def test_builder_skills_section_gated(tmp_path):
    ws = _make_skills_dir(tmp_path)
    mgr = SkillManager(ws / "skills").refresh()
    # 没 manager → 没技能段
    assert "技能系统" not in build_system_prompt()
    # 有 manager 但没技能 → 也没技能段
    empty = SkillManager(tmp_path / "空").refresh()
    assert "技能系统" not in build_system_prompt(skill_manager=empty)
    # 有技能 → 技能段 + 使用纪律 + 描述清单
    p = build_system_prompt(skill_manager=mgr)
    assert "技能系统" in p and "技能不是工具" in p and "read_file" in p
    assert "weekly-report" in p and "整理成结构化周报" in p
    # 关键：正文不进 prompt（两段式——正文由模型按需 read_file）
    assert "先问用户本周干了什么" not in p


# ---------- 装配间集成 ----------

class _StubBot:
    def chat(self, *a, **kw):
        raise NotImplementedError


def test_initializer_wires_skills(tmp_path):
    ws = _make_skills_dir(tmp_path)
    agent = initialize_agent(bot=_StubBot(), workspace_dir=ws)
    assert "weekly-report" in agent.system_prompt
    assert "整理成结构化周报" in agent.system_prompt
