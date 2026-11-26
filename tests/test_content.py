# -*- coding: utf-8 -*-
"""仓库内容一致性校验（不驱动安装器，无平台分支）。

--verify 只校验铁律编号是 1-10，校验不到 Skill 按编号引用的条文标题；
这些断言补上这一层，防止条文修改后编号引用悄悄失效。
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _iron_rules_with_anchors():
    """解析 AGENTS.md：`<!-- iron:xxx -->` 注释行与其后第一条 'N. **标题**' 配对。"""
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    rules, pairs = {}, []
    pending = None
    for line in text.splitlines():
        m = re.match(r"<!--\s*(iron:[a-z0-9-]+)\s*-->", line.strip())
        if m:
            pending = m.group(1)
            continue
        m = re.match(r"(\d+)\. \*\*(.+?)\*\*", line)
        if m:
            num, title = int(m.group(1)), m.group(2)
            rules[num] = title
            if pending is not None:
                pairs.append((pending, num, title))
                pending = None
    return rules, pairs


def test_iron_rule_anchors():
    """铁律条目各带稳定锚点 ID；skill/README 按锚点引用，不再跨文档按编号耦合。

    原防护意图（防止条文修改后引用悄悄失效）改为：锚点存在性 + 被引用锚点的
    条文标题关键词绑定 + 编号引用残留守卫。AGENTS.md 条内互引仍用编号（受
    1-10 完整性断言守护）。
    """
    rules, pairs = _iron_rules_with_anchors()
    assert sorted(rules) == list(range(1, 11)), "铁律应为 1-10 且无缺号"
    ids = [pid for pid, _, _ in pairs]
    assert len(ids) == 10 and len(set(ids)) == 10, f"应有 10 个唯一 iron: 锚点，实际 {ids}"
    anchors = {pid: title for pid, _, title in pairs}
    assert "事实" in anchors["iron:fact-source"], "iron:fact-source 应绑定「事实与数据底线」"
    assert "可恢复" in anchors["iron:recoverable"], "iron:recoverable 应绑定「修改前可恢复」"
    scan = list((REPO / "skills").rglob("*.md")) + [REPO / "README.md"]
    for p in scan:
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"iron:[a-z0-9-]+", text):
            assert m.group(0) in anchors, f"{p.name} 引用了未知锚点 {m.group(0)}"
        assert not re.search(r"铁律第\s*\d+", text), f"{p.name} 仍按编号引用铁律，应改为 iron: 锚点"


def test_backup_format_matches_iron_rule_2():
    """铁律第 2 条写明备份命名格式；安装器的实现必须逐字一致。"""
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "<原名>_YYYYMMDD_HHMMSS.<原扩展名>.bak" in text
    assert "A_20260101_000000_2.md.bak" in text, "重名格式应含具体示例"


def test_annotation_vocabulary_uniform():
    """标注词汇应统一为一套（AGENTS.md 的方括号体系）。"""
    for p in (REPO / "skills").glob("*/SKILL.md"):
        text = p.read_text(encoding="utf-8")
        assert "【需验证】" not in text, f"{p.name} 仍有【需验证】"
        assert "【估算】" not in text, f"{p.name} 仍有【估算】"


def test_installer_version_matches_engine():
    ps1 = (REPO / "install.ps1").read_bytes().decode("utf-8-sig")
    core = (REPO / "scripts" / "sync_lib" / "core.py").read_text(encoding="utf-8")
    m1 = re.search(r"^\$VERSION = '([^']+)'", ps1, re.M)
    m2 = re.search(r'^VERSION = "([^"]+)"', core, re.M)
    assert m1 and m2 and m1.group(1) == m2.group(1), "入口与引擎 VERSION 应一致"


def test_line_count_within_limit():
    targets = list((REPO / "scripts").rglob("*.py")) + list((REPO / "tests").glob("*.py")) + [REPO / "install.ps1"]
    for path in targets:
        if not path.exists():
            continue
        text = path.read_bytes().decode("utf-8-sig")
        lines = text.count("\n") + (0 if text.endswith("\n") else 1)
        rel = path.relative_to(REPO).as_posix()
        assert lines <= 600, f"{rel} 超过 600 行上限: {lines}"


def test_skill_main_size_within_limit():
    """动态遍历：主 SKILL.md 不超过 10KB 警戒阈值（细则应在 references/）。"""
    for d in (REPO / "skills").iterdir():
        if not d.is_dir():
            continue
        skill = d / "SKILL.md"
        size = skill.stat().st_size
        assert size <= 10 * 1024, f"skills/{d.name}/SKILL.md 超过 10KB（{size}B），请拆层到 references/"


def test_idea_eval_main_size():
    """idea-evaluation 主文件只留决策骨架与红线（目标 5KB，验收线 5.5KB）。"""
    skill = REPO / "skills" / "zhuoh-idea-evaluation" / "SKILL.md"
    size = skill.stat().st_size
    assert size <= 5632, f"idea-evaluation SKILL.md {size}B 超 5.5KB，继续拆层到 references/"


def test_paper_writing_main_size():
    """paper-writing 主文件只留决策骨架与红线（目标 5KB，验收线 5.5KB）。"""
    skill = REPO / "skills" / "zhuoh-paper-writing" / "SKILL.md"
    size = skill.stat().st_size
    assert size <= 5632, f"paper-writing SKILL.md {size}B 超 5.5KB，继续拆层到 references/"


def test_skill_names_prefixed():
    """动态遍历：Skill 目录名与 frontmatter name 必须带 zhuoh- 前缀且一致。"""
    dirs = sorted(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
    assert dirs, "skills/ 下至少应有一个技能"
    assert all(d.startswith("zhuoh-") for d in dirs), f"技能目录名必须带 zhuoh- 前缀: {dirs}"
    for d in (REPO / "skills").iterdir():
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r"(?m)^name:\s*(\S+)", text)
        assert m and m.group(1) == d.name, f"{d.name} 的 frontmatter name 不一致"
        m2 = re.search(r"(?m)^description:\s*(\S+)", text)
        assert m2 and m2.group(1), f"{d.name} 的 frontmatter 缺 description"


def test_readme_has_no_hardcoded_version():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"(?<!\d)\d+\.\d+\.\d+(?!\d)", text), "README 不应写死任何三段式版本号"


def test_gbt_2025_default():
    pw = (REPO / "skills" / "zhuoh-paper-writing" / "SKILL.md").read_text(encoding="utf-8")
    assert "GB/T 7714—2025" in pw
    assert "据称已发布" not in pw, "2025 版发布状态已核实，不应再写据称/未经核实"
    assert "[DS/OL]" in pw and "[PP/OL]" in pw, "2025 版新增类型应已落地"


def test_docs_use_windows_entrypoint():
    for name in ("README.md", "BOOTSTRAP.md", "prompts/sync.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "python install.py" not in text, f"{name} 仍引用 python install.py"
        assert "install.ps1" in text, f"{name} 应引用 Windows 入口 install.ps1"
        assert "install.sh" not in text, f"{name} 不应再引用已移除的 POSIX 入口"


def test_posix_entrypoint_removed():
    assert not (REPO / "install.sh").exists(), "本仓库仅维护 Windows，POSIX 入口应已移除"


def test_install_ps1_windowsapps_regex_escaped():
    ps1 = (REPO / "install.ps1").read_bytes().decode("utf-8-sig")
    assert r"WindowsApps\\python3?\.exe$" in ps1, "install.ps1 过滤 WindowsApps 的正则反斜杠转义错误"
