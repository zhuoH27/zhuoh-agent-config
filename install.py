#!/usr/bin/env python3
"""Install agent-config rules and skills into a local agent host.
Targets:
  claude  -> ~/.claude/CLAUDE.md + ~/.claude/skills/
  codex   -> ~/.codex/AGENTS.md + ~/.codex/skills/
  agents  -> ~/.agents/AGENTS.md + ~/.agents/skills/
Examples:
  python install.py --dry-run --target auto
  python install.py --apply --target claude
  python install.py --verify --target claude
Notes:
  仅使用标准库；无网络访问、无子进程调用。
  读取按 UTF-8 解码（兼容 BOM）并保留原始换行符；非 UTF-8 文件以可读错误停止。
  写入一律 UTF-8 无 BOM；已有文件的换行风格（LF/CRLF）沿用原文件。
  带 BOM 的旧文件在任何写入时都会顺带剥离 BOM；区块已最新但文件带 BOM 时，
  apply 会原样重写一次仅剥 BOM（先备份）。
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

BEGIN_MARK = "<!-- BEGIN: global-iron-rules -->"
END_MARK = "<!-- END: global-iron-rules -->"
SKILL_NAMES = ["code-standards", "ppt-maker", "paper-writing", "idea-evaluation"]
KNOWN_OVERLAPS = {
    "coding-standards": "code-standards",
    "academic-pptx": "ppt-maker",
    "nature-paper2ppt": "ppt-maker",
    "scientific-figure-making": "ppt-maker",
    "anti-defensive-writing": "paper-writing",
}
REPO = Path(__file__).resolve().parent
VERSION = "1.1.1"
TS_HINT = "YYYYMMDD_HHMMSS"
BOM = b"\xef\xbb\xbf"
LEGACY_HINTS = ("全局核心铁律", "不可逆操作确认")


@dataclass
class Host:
    key: str
    label: str
    root: Path
    rules: Path
    skills: Path


@dataclass
class RulesPlan:
    action: str
    target: Path
    reason: str
    backup_hint: Optional[Path] = None


@dataclass
class SkillPlan:
    name: str
    action: str
    target: Path
    reason: str
    others: List[str] = field(default_factory=list)
    backup_hint: Optional[Path] = None


def host_for(key: str, home: Path) -> Host:
    labels = {"claude": "Claude Code", "codex": "Codex CLI", "agents": "~/.agents 约定"}
    root = home / ("." + key)
    rules_name = "CLAUDE.md" if key == "claude" else "AGENTS.md"
    return Host(key, labels[key], root, root / rules_name, root / "skills")


def read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SystemExit(
            "无法按 UTF-8 解码 %s（%s）。若文件是 GBK/UTF-16 等编码，"
            "请先转成 UTF-8 再运行；脚本不猜测编码。" % (path, exc)
        )


def has_bom(path: Path) -> bool:
    try:
        return path.read_bytes().startswith(BOM)
    except OSError:
        return False


def newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized(text: str, nl: str = "\n") -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", nl)


def extract_block(text: str) -> str:
    i = text.find(BEGIN_MARK)
    j = text.find(END_MARK)
    if i < 0 or j < 0 or j < i:
        raise ValueError("受管标记不完整")
    return text[i : j + len(END_MARK)].strip("\r\n")


def load_source_rules() -> str:
    path = REPO / "AGENTS.md"
    if not path.is_file():
        raise SystemExit("缺少源规则文件: %s" % path)
    text = read_text(path)
    if text.count(BEGIN_MARK) != 1 or text.count(END_MARK) != 1:
        raise SystemExit("源 AGENTS.md 的受管标记不成对")
    if text.find(END_MARK) < text.find(BEGIN_MARK):
        raise SystemExit("源 AGENTS.md 的 END 在 BEGIN 之前")
    return extract_block(text)


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_filename(name: str, ts: str) -> str:
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        return "%s_%s.%s.bak" % (stem, ts, ext)
    return "%s_%s.bak" % (name, ts)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name("%s_%d%s" % (path.stem, n, path.suffix))
        if not candidate.exists():
            return candidate
        n += 1


def block_diff(target: Path) -> str:
    old = extract_block(read_text(target))
    new = load_source_rules()
    lines = difflib.unified_diff(
        normalized(old).splitlines(),
        normalized(new).splitlines(),
        fromfile="已安装",
        tofile="仓库",
        lineterm="",
    )
    return "\n".join(lines)


def plan_rules(host: Host, mode: str) -> RulesPlan:
    target = host.rules
    if target.is_symlink():
        raise SystemExit("规则文件是符号链接，拒绝写入: %s" % target)
    if not target.exists():
        return RulesPlan("create", target, "规则文件不存在，将新建")
    text = read_text(target)
    size = target.stat().st_size
    begins = text.count(BEGIN_MARK)
    ends = text.count(END_MARK)
    if begins == 1 and ends == 1 and text.find(END_MARK) >= text.find(BEGIN_MARK):
        block = extract_block(text)
        source = load_source_rules()
        if normalized(block) == normalized(source):
            if has_bom(target):
                return RulesPlan(
                    "rewrite",
                    target,
                    "受管区块已是最新，但文件带 BOM；将备份后原样重写（仅剥离 BOM）",
                    host.root / "_backup" / backup_filename(target.name, TS_HINT),
                )
            return RulesPlan("skip", target, "受管区块已是最新")
        return RulesPlan(
            "replace_block",
            target,
            "将替换受管区块",
            host.root / "_backup" / backup_filename(target.name, TS_HINT),
        )
    if begins or ends:
        raise SystemExit(
            "标记异常: %s (BEGIN=%d, END=%d)；请先手动修复，脚本不自动修"
            % (target, begins, ends)
        )
    if size == 0:
        return RulesPlan("create", target, "规则文件为空，将写入")
    if not text.strip():
        return RulesPlan(
            "replace_file",
            target,
            "规则文件仅含空白，备份后写入",
            host.root / "_backup" / backup_filename(target.name, TS_HINT),
        )
    if mode == "abort":
        raise SystemExit("%s 已有内容但没有受管标记；按 --mode abort 停止" % target)
    if mode == "replace":
        return RulesPlan(
            "replace_file",
            target,
            "按 --mode replace 整文件替换",
            host.root / "_backup" / backup_filename(target.name, TS_HINT),
        )
    reason = "已有内容无标记，将追加受管区块（保留原内容）"
    if any(hint in text for hint in LEGACY_HINTS):
        reason += (
            "；[警告] 疑似已有旧版未受管铁律，直接追加会重复或冲突，"
            "请人工合并，或经用户确认后改用 --mode replace"
        )
    return RulesPlan(
        "append",
        target,
        reason,
        host.root / "_backup" / backup_filename(target.name, TS_HINT),
    )


def plan_skill(host: Host, name: str) -> SkillPlan:
    source = REPO / "skills" / name / "SKILL.md"
    if not source.is_file():
        raise SystemExit("缺少源 Skill: %s" % source)
    target = host.skills / name / "SKILL.md"
    if target.is_symlink():
        raise SystemExit("Skill 文件是符号链接，拒绝写入: %s" % target)
    others: List[str] = []
    if target.parent.exists():
        others = sorted(
            p.name for p in target.parent.iterdir() if p.is_file() and p.name != "SKILL.md"
        )
    if not target.exists():
        return SkillPlan(name, "create", target, "将新建", others=others)
    old = read_text(target)
    new = read_text(source)
    if normalized(old) == normalized(new):
        return SkillPlan(name, "skip", target, "已是最新", others=others)
    return SkillPlan(
        name,
        "replace",
        target,
        "将备份后覆盖 SKILL.md",
        others=others,
        backup_hint=host.root / "_backup" / "skills" / name / backup_filename("SKILL.md", TS_HINT),
    )


def print_plan(host: Host, rules: RulesPlan, skills: List[SkillPlan]) -> None:
    print("\n宿主: %s (%s)" % (host.label, host.key))
    print("  根目录: %s" % host.root)
    print("  规则文件: %s" % host.rules)
    print("  Skills 目录: %s" % host.skills)
    print("  规则处理: %s - %s" % (rules.action, rules.reason))
    if rules.backup_hint:
        print("    将备份到: %s" % rules.backup_hint)
    if rules.action == "replace_block":
        for line in block_diff(rules.target).splitlines():
            print("    " + line)
    for skill in skills:
        print("  Skill %s: %s - %s" % (skill.name, skill.action, skill.reason))
        if skill.backup_hint:
            print("    将备份到: %s" % skill.backup_hint)
        if skill.others:
            print("    目录内其他文件（不会改动）: %s" % ", ".join(skill.others))
    if host.skills.exists():
        existing = sorted(
            p.name for p in host.skills.iterdir() if p.is_dir() and p.name not in SKILL_NAMES
        )
        if existing:
            print("  现有其他 Skill（不会改动）: %s" % ", ".join(existing))
            overlaps = [
                "%s ≈ %s" % (name, KNOWN_OVERLAPS[name])
                for name in existing
                if name in KNOWN_OVERLAPS
            ]
            if overlaps:
                print("  可能功能重叠（仅提醒，不删除）: %s" % ", ".join(overlaps))


def do_backup(desired: Path, source: Path) -> Path:
    desired.parent.mkdir(parents=True, exist_ok=True)
    dest = unique_path(desired)
    shutil.copy2(source, dest)
    return dest


def apply_rules(host: Host, plan: RulesPlan, ts: str) -> Tuple[str, Optional[Path]]:
    if plan.action == "skip":
        return "跳过", None
    target = plan.target
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Optional[Path] = None
    if target.exists() and target.stat().st_size > 0:
        backup = do_backup(
            host.root / "_backup" / backup_filename(target.name, ts), target
        )
    source = load_source_rules()
    if plan.action == "create":
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(normalized(source, "\n") + "\n")
        return "新建", backup
    if plan.action == "rewrite":
        raw = target.read_bytes()
        with target.open("wb") as handle:
            handle.write(raw[len(BOM) :] if raw.startswith(BOM) else raw)
        return "剥离 BOM 原样重写", backup
    old = read_text(target)
    nl = newline_of(old)
    if plan.action == "replace_block":
        i = old.find(BEGIN_MARK)
        j = old.find(END_MARK)
        if i < 0 or j < 0:
            raise SystemExit("受管标记在写入前消失: %s" % target)
        new_text = old[:i] + normalized(source, nl) + old[j + len(END_MARK) :]
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        return "替换受管区块", backup
    if plan.action == "append":
        new_text = old.rstrip("\r\n") + nl + nl + normalized(source, nl) + nl
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        return "追加受管区块", backup
    if plan.action == "replace_file":
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(normalized(source, nl) + nl)
        return "整文件替换", backup
    raise SystemExit("未知规则动作: %s" % plan.action)


def apply_skill(host: Host, plan: SkillPlan, ts: str) -> Tuple[str, Optional[Path]]:
    if plan.action == "skip":
        return "跳过", None
    target = plan.target
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Optional[Path] = None
    if target.exists():
        backup = do_backup(
            host.root / "_backup" / "skills" / plan.name / backup_filename("SKILL.md", ts),
            target,
        )
    source = read_text(REPO / "skills" / plan.name / "SKILL.md")
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write(normalized(source, "\n"))
    return ("新建" if plan.action == "create" else "覆盖"), backup


def verify(host: Host) -> bool:
    ok = True
    print("\n=== 校验 %s (%s) ===" % (host.label, host.key))
    print("规则文件: %s" % host.rules)
    if not host.rules.is_file():
        print("  FAIL: 规则文件不存在")
        return False
    raw = host.rules.read_bytes()
    text = read_text(host.rules)
    begins = text.count(BEGIN_MARK)
    ends = text.count(END_MARK)
    block = ""
    if begins != 1 or ends != 1 or text.find(END_MARK) < text.find(BEGIN_MARK):
        print("  FAIL: 标记异常 BEGIN=%d END=%d" % (begins, ends))
        ok = False
    else:
        block = extract_block(text)
        source = load_source_rules()
        match = normalized(block) == normalized(source)
        digest = sha256_text(normalized(block) + "\n")[:12]
        print(
            "  受管区块: %s (%d 行, sha256 %s)"
            % ("OK" if match else "FAIL", len(block.splitlines()), digest)
        )
        if not match:
            ok = False
    if "# 全局核心铁律" not in text:
        print("  FAIL: 缺少标题“全局核心铁律”")
        ok = False
    if block:
        numbers = sorted(set(int(m.group(1)) for m in re.finditer(r"^(\d+)\. \*\*", block, re.M)))
        if numbers != list(range(1, 11)):
            print("  FAIL: 铁律编号不是 1-10: %s" % numbers)
            ok = False
        else:
            print("  铁律条数: OK (1-10)")
    print("  BOM: %s" % ("FAIL (存在 BOM)" if raw.startswith(BOM) else "OK (无)"))
    if raw.startswith(BOM):
        ok = False
    print("  换行: %s" % ("CRLF（沿用原文件）" if b"\r\n" in raw else "LF"))
    for name in SKILL_NAMES:
        target = host.skills / name / "SKILL.md"
        print("Skill %s: %s" % (name, target))
        if not target.is_file():
            print("  FAIL: 文件不存在")
            ok = False
            continue
        skill_raw = target.read_bytes()
        skill_text = read_text(target)
        source = read_text(REPO / "skills" / name / "SKILL.md")
        match = normalized(skill_text) == normalized(source)
        digest = sha256_text(normalized(skill_text))[:12]
        print(
            "  %s (%d 行, sha256 %s)"
            % ("OK" if match else "FAIL", len(skill_text.splitlines()), digest)
        )
        if not match:
            ok = False
        if not skill_text.startswith("---"):
            print("  FAIL: 缺少 YAML frontmatter")
            ok = False
        else:
            fm_end = skill_text.find("\n---", 3)
            front = skill_text[:fm_end] if fm_end >= 0 else ""
            m_name = re.search(r"^name:\s*(\S+)\s*$", front, re.M)
            if not m_name or m_name.group(1).strip("\"'") != name:
                print("  FAIL: frontmatter 的 name 缺失或与目录名不一致")
                ok = False
            m_desc = re.search(r"^description:\s*(.+)$", front, re.M)
            if not m_desc or m_desc.group(1).strip().strip("\"'") in ("", ">", "|", ">-", "|-"):
                print("  FAIL: frontmatter 缺少单行 description")
                ok = False
        if skill_raw.startswith(BOM):
            print("  FAIL: 存在 BOM")
            ok = False
        if b"\r\n" in skill_raw:
            print("  FAIL: 存在 CRLF")
            ok = False
    return ok


def resolve_targets(target: str, home: Path) -> List[Host]:
    if target == "auto":
        signal = None
        if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
            signal = "claude"
        elif os.environ.get("CODEX_SANDBOX") or os.environ.get("CODEX_THREAD_ID"):
            signal = "codex"
        if signal:
            print("检测依据: 环境变量 -> %s" % signal)
            return [host_for(signal, home)]
        existing = [k for k in ("claude", "codex") if (home / ("." + k)).exists()]
        if len(existing) == 1:
            print("检测依据: 仅存在 ~/.%s -> %s" % (existing[0], existing[0]))
            return [host_for(existing[0], home)]
        if len(existing) == 2:
            raise SystemExit(
                "同时检测到 ~/.claude 与 ~/.codex，无法唯一确定宿主。\n"
                "请用 --target claude、--target codex 或 --target both 明确指定。"
            )
        raise SystemExit(
            "未检测到 ~/.claude 或 ~/.codex，请用 --target 明确指定（可先创建对应目录）。"
        )
    if target == "both":
        return [host_for("claude", home), host_for("codex", home)]
    return [host_for(target, home)]


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 agent-config 的全局规则与 4 个 Skill")
    parser.add_argument(
        "--target",
        choices=["auto", "claude", "codex", "agents", "both"],
        default="auto",
        help="目标宿主，默认 auto",
    )
    parser.add_argument(
        "--mode",
        choices=["append", "replace", "abort"],
        default="append",
        help="规则文件已有内容但无标记时的处理方式，默认 append",
    )
    parser.add_argument("--home", type=Path, default=None, help="测试用：替换用户主目录")
    parser.add_argument("--version", action="version", version="agent-config %s" % VERSION)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="只展示计划，不写入")
    group.add_argument("--apply", action="store_true", help="执行写入")
    group.add_argument("--verify", action="store_true", help="校验已安装文件")
    args = parser.parse_args()
    home = args.home.expanduser() if args.home else Path.home()
    hosts = resolve_targets(args.target, home)
    if args.verify:
        all_ok = True
        for host in hosts:
            all_ok = verify(host) and all_ok
        print("\n结论: %s" % ("全部通过" if all_ok else "存在失败项"))
        return 0 if all_ok else 1
    plans = []
    for host in hosts:
        rules = plan_rules(host, args.mode)
        skills = [plan_skill(host, name) for name in SKILL_NAMES]
        plans.append((host, rules, skills))
    for host, rules, skills in plans:
        print_plan(host, rules, skills)
    if not args.apply:
        print("\n以上为 dry-run（未写入任何文件）。确认后用 --apply 执行。")
        return 0
    ts = timestamp()
    written: List[str] = []
    backups: List[Tuple[Path, Path]] = []
    skipped: List[str] = []
    try:
        for host, rules, skills in plans:
            status, backup = apply_rules(host, rules, ts)
            (written if status != "跳过" else skipped).append("%s 规则: %s" % (host.key, status))
            if backup:
                backups.append((backup, rules.target))
            for skill in skills:
                status, backup = apply_skill(host, skill, ts)
                if status == "跳过":
                    skipped.append("%s Skill %s: 已最新" % (host.key, skill.name))
                else:
                    written.append("%s Skill %s: %s" % (host.key, skill.name, status))
                if backup:
                    backups.append((backup, skill.target))
    except (Exception, SystemExit) as exc:
        print("\n失败: %s" % exc)
        print("已写入: %s" % ("; ".join(written) if written else "无"))
        if backups:
            print("已备份（把备份复制回箭头右侧原路径即可回滚，脚本不自动回滚）:")
            for backup, original in backups:
                print("  %s -> %s" % (backup, original))
        else:
            print("已备份: 无")
        print("未处理: 其余")
        return 1
    print("\n=== 执行结果 ===")
    for item in written:
        print("写入: %s" % item)
    for backup, _original in backups:
        print("备份: %s" % backup)
    for item in skipped:
        print("跳过: %s" % item)
    print("\n下一步: python install.py --verify --target %s" % args.target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
