# -*- coding: utf-8 -*-
"""仓库内容一致性校验（不驱动安装器，无平台分支）。

--verify 只校验铁律编号是 1-10，校验不到 Skill 按编号引用的条文标题；
这些断言补上这一层，防止条文修改后编号引用悄悄失效。
"""
import json
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
    # 10 组锚点全量语义绑定：锚点被换位/错绑即失败，而非只抽查两个
    expected = {
        "iron:confirm": "确认",
        "iron:recoverable": "可恢复",
        "iron:fact-source": "事实",
        "iron:verify-first": "验证",
        "iron:task-grades": "分级",
        "iron:first-principles": "第一性",
        "iron:report-four": "汇报",
        "iron:fuse": "熔断",
        "iron:handoff": "交接",
        "iron:priority": "优先级",
    }
    assert set(anchors) == set(expected), f"锚点集合不符，应为 {sorted(expected)}"
    for pid, keyword in expected.items():
        assert keyword in anchors[pid], f"{pid} 应绑定含「{keyword}」的条文标题，实际「{anchors[pid]}」"
    scan = list((REPO / "skills").rglob("*.md")) + [REPO / "README.md", REPO / "AGENTS.md"]
    for p in scan:
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"iron:[a-z0-9-]+", text):
            assert m.group(0) in anchors, f"{p.name} 引用了未知锚点 {m.group(0)}"
        if p.name != "AGENTS.md":  # AGENTS.md 条内互引按编号属约定豁免
            assert not re.search(r"铁律第\s*\d+", text), f"{p.name} 仍按编号引用铁律，应改为 iron: 锚点"


def test_pptx_skill_references_script():
    """SKILL.md 应引用 scripts/set_fonts.py 而非内嵌实现（防文档与测试再度漂移）。

    纯文本断言，故不放在 tests/test_pptx_font.py（那边 importorskip pptx 会连坐跳过）。
    """
    skill = (REPO / "skills" / "zhuoh-ppt-maker" / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/set_fonts.py" in skill
    assert "def set_run_fonts" not in skill, "SKILL.md 不应内嵌实现，应引用 scripts/set_fonts.py"


def test_backup_format_matches_iron_rule_2():
    """铁律 iron:recoverable（修改前可恢复）写明备份命名格式；安装器实现必须逐字一致。"""
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


def test_manifest_skill_versions_match():
    """manifest.json skill_versions 与各 SKILL.md frontmatter metadata.version 对账。

    SKILL.md 是权威源，manifest 为镜像；双写由本测试兜住，覆盖 skills/
    全部技能目录（新增技能忘登记即失败）。
    """
    manifest = json.loads((REPO / "manifest.json").read_text(encoding="utf-8"))
    versions = manifest.get("skill_versions", {})
    dirs = sorted(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
    assert sorted(versions) == dirs, "manifest skill_versions 应覆盖全部技能目录且无多余项"
    for d in dirs:
        text = (REPO / "skills" / d / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r'(?ms)^metadata:\s*\n\s+version:\s*"([^"]+)"', text)
        assert m, f"{d} 的 SKILL.md 缺 metadata.version"
        assert m.group(1) == versions[d], f"{d} 版本不一致：SKILL.md={m.group(1)} manifest={versions[d]}"


def test_manifest_zcode_host_managed():
    """zcode 宿主受管：root=~/.zcode、规则 AGENTS.md、技能目录 skills（防宿主清单漏项漂移）。"""
    hosts = json.loads((REPO / "manifest.json").read_text(encoding="utf-8"))["hosts"]
    cfg = hosts.get("zcode", {})
    assert cfg.get("root") == "~/.zcode"
    assert cfg.get("rules_target") == "AGENTS.md"
    assert cfg.get("skills_dir") == "skills"


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


def test_gbt_version_single_sourced():
    """GB/T 7714 版本信息单点维护于 templates.md；body 只引「最新版」不带年份。

    原 test_gbt_2025_default 的防护意图（默认标准已落地、发布状态已核实、
    新增类型已落地）改由「templates.md 单点存在 + body 无年份复写 + 禁用
    对冲话术」承载。
    """
    base = REPO / "skills" / "zhuoh-paper-writing"
    skill = (base / "SKILL.md").read_text(encoding="utf-8")
    tpl = (base / "references" / "templates.md").read_text(encoding="utf-8")
    assert "GB/T 7714—2025" in tpl and "2025-12-02" in tpl and "2026-07-01" in tpl, "templates.md 应为版本权威单点（版本号+发布/实施日期）"
    assert "最新版 GB/T 7714" in skill, "body 应按「最新版」引用"
    assert not re.search(r"7714[\s—–-]*20\d\d", skill), "body 不应复写版本年份（含 ASCII 连字符/裸年份），版本信息单点在 templates.md"
    assert "据称已发布" not in skill and "据称已发布" not in tpl, "发布状态已核实，不应再写据称/未经核实"
    assert "[DS/OL]" in tpl and "[PP/OL]" in tpl, "2025 版新增类型应在 templates.md 落地"


def test_reference_files_exist_and_linked():
    """细则拆层最低守卫：body 指针 → 文件存在 → 关键节标题在，防止拆层时细则被静默丢弃。"""
    ie = REPO / "skills" / "zhuoh-idea-evaluation"
    pw = REPO / "skills" / "zhuoh-paper-writing"
    ie_body = (ie / "SKILL.md").read_text(encoding="utf-8")
    pw_body = (pw / "SKILL.md").read_text(encoding="utf-8")
    assert "references/rubric.md" in ie_body, "idea-eval body 应指向 references/rubric.md"
    assert "references/templates.md" in pw_body, "paper-writing body 应指向 references/templates.md"
    assert "references/review-guide.md" in pw_body, "paper-writing body 应指向 references/review-guide.md"
    rubric = (ie / "references" / "rubric.md").read_text(encoding="utf-8")
    for title in ("裁决类别判定细则", "置信度细则", "验证清单细则", "角色话术与论点判据"):
        assert title in rubric, f"rubric.md 缺关键节「{title}」"
    tpl = (pw / "references" / "templates.md").read_text(encoding="utf-8")
    for title in ("顺序编码制细则", "七项原则判据细则"):
        assert title in tpl, f"templates.md 缺关键节「{title}」"
    review = (pw / "references" / "review-guide.md").read_text(encoding="utf-8")
    for title in ("逐部分检查标准", "常见失败模式清单"):
        assert title in review, f"review-guide.md 缺关键节「{title}」"


def test_layered_details_survive_extraction():
    """抽取细则的行为红线与判据要素不得丢失（终审红队 F1-F3 回归防线）。"""
    rubric = (REPO / "skills" / "zhuoh-idea-evaluation" / "references" / "rubric.md").read_text(encoding="utf-8")
    for phrase in ("不揣测动机", "修辞偏差", "钱/时间/机会成本", "只看未来追加投入与回报", "点出关键问题"):
        assert phrase in rubric, f"rubric.md 丢失关键细则「{phrase}」"
    tpl = (REPO / "skills" / "zhuoh-paper-writing" / "references" / "templates.md").read_text(encoding="utf-8")
    for phrase in ("标题、摘要、引言、综述、正文、讨论、结论与展望", "因变量居右", "类比/推断/个例"):
        assert phrase in tpl, f"templates.md 丢失关键细则「{phrase}」"


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
