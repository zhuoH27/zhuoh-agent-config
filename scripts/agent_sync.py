# -*- coding: utf-8 -*-
"""agent-config 核心同步引擎（Python 3 标准库，无外部依赖）。

命令面：setup / doctor / sync-back / audit / status。
行为契约继承原 install.sh / install.ps1 v2.2.0：auto 探测（环境变量优先）、
规则文件 append/replace/abort、受管标记防护、换行沿用、BOM 剥离、UTF-8
强校验、备份命名 <原名>_<TS>.<ext>.bak（重名 _2/_3）、原子写入、链接目标
拒绝写入。备份统一存 ~/.zhuoh-agent-backup/<TS>/，不污染技能目录。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

VERSION = "3.0.0"
REPO = Path(__file__).resolve().parent.parent
BEGIN_MARK = "<!-- BEGIN: global-iron-rules -->"
END_MARK = "<!-- END: global-iron-rules -->"
TS_RE = re.compile(r"^\d{8}_\d{6}$")
SKILL_SIZE_WARN = 10 * 1024
STATE_FILE = ".sync-state.json"
AUDIT_EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", "_backup", "node_modules"}
AUDIT_EXCLUDE_DIRS.add("tests")   # 测试文件内置假密钥样本，不参与审计
AUDIT_EXCLUDE_DIRS.add("_t*")     # pytest tmp 工件
AUDIT_TEXT_SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".sh", ".ps1", ".txt",
                       ".toml", ".cfg", ".ini", ".html", ".css", ".js", ".ts"}
SECRET_PATTERNS = tuple((re.compile(p), n) for p, n in (
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI 风格 API Key"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"xox[bapr]-[A-Za-z0-9-]{10,}", "Slack Token"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "私钥"),
    (r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_.-]{16,}['\"]", "API Key 赋值"),
    (r"(?i)(?:secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_.-]{16,}['\"]", "凭据赋值")))
PATH_PATTERNS = tuple(re.compile(p) for p in (
    r"[A-Za-z]:\\Users\\[^\s\"'`]+", r"[A-Za-z]:/Users/",
    r"(?<![\w/])/Users/[A-Za-z0-9_-]+/", r"(?<![\w/])/home/[A-Za-z0-9_-]+/"))

def die(msg, code=1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

def ts_now():
    v = os.environ.get("AGENT_CONFIG_TS", "")
    return v if TS_RE.match(v) else time.strftime("%Y%m%d_%H%M%S")

def expand_user(p, home):
    s = str(p)
    if s == "~":
        return home
    if s.startswith("~/") or s.startswith("~\\"):
        return home / s[2:]
    return Path(s)

def home_base(args_home):
    if args_home:
        return expand_user(args_home, Path.home()).resolve()
    h = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not h:
        die("HOME/USERPROFILE 未设置，无法定位宿主目录；请设置或用 --home 指定")
    return Path(h).resolve()

def norm_text(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return str(raw).replace("\r\n", "\n").replace("\r", "\n")

def read_utf8(path):
    try:
        return Path(path).read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as e:
        print(f"错误: {path} 无法按 UTF-8 解码，请先转换为 UTF-8（{e}）", file=sys.stderr)
        sys.exit(1)

def sha256_norm(path):
    try:
        return hashlib.sha256(norm_text(Path(path).read_bytes()).encode("utf-8")).hexdigest()
    except OSError:
        return None

def detect_eol(text):
    return "\r\n" if "\r\n" in text else "\n"

def atomic_write(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".agent_tmp")
    tmp.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    os.replace(tmp, p)

def points_to(target, src):
    try:
        return Path(os.path.realpath(target)) == Path(os.path.realpath(src))
    except OSError:
        return False

def make_backup(root, path, ts, dry_run=False):
    """~/.zhuoh-agent-backup/<TS>/<原名>_<TS>.<ext>.bak，重名 _2/_3 递增。"""
    p = Path(path)
    stem = p.stem if p.suffix else p.name
    d = root / ts
    cand = d / f"{stem}_{ts}{p.suffix}.bak"
    n = 2
    while cand.exists():
        cand = d / f"{stem}_{ts}_{n}{p.suffix}.bak"
        n += 1
    if not dry_run:
        cand.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, cand)
    return cand


class Manifest:
    def __init__(self, repo):
        try:
            data = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            die(f"manifest.json 解析失败: {e}")
        self.backup_root_name = data.get("backup_root", "~/.zhuoh-agent-backup")
        self.default_mode = data.get("default_mode", "copy")
        if self.default_mode not in ("copy", "link"):
            die(f"manifest default_mode 非法: {self.default_mode}")
        self.hosts = data.get("hosts", {})
        self.overlaps = data.get("known_overlaps", {})
        if not self.hosts:
            die("manifest hosts 为空")

    def rules_path(self, key, home):
        c = self.hosts[key]
        return expand_user(c["root"], home) / c.get("rules_target", "AGENTS.md")

    def skills_dir(self, key, home):
        return expand_user(self.hosts[key]["root"], home) / "skills"

    def prompts_dir(self, key, home):
        return expand_user(self.hosts[key]["root"], home) / self.hosts[key].get("prompts_dir", "")

    def backup_root(self, home):
        return expand_user(self.backup_root_name, home)

def resolve_targets(target_arg, mf, home, env=None):
    env = os.environ if env is None else env
    known = list(mf.hosts)
    if target_arg == "auto":
        if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
            return ["claude"], "环境变量 -> claude"
        if env.get("CODEX_THREAD_ID"):
            return ["codex"], "环境变量 -> codex"
        existing = [k for k in known if expand_user(mf.hosts[k]["root"], home).exists()]
        if "claude" in existing and "codex" in existing:
            die("同时检测到 ~/.claude 与 ~/.codex，无法唯一确定宿主。\n"
                "请用 --target claude、--target codex 或 --target both 明确指定。")
        if len(existing) == 1:
            k = existing[0]
            label = {"claude": "仅存在 ~/.claude", "codex": "仅存在 ~/.codex"}.get(
                k, f"仅存在 {mf.hosts[k]['root']}")
            return [k], label
        die("未检测到 ~/.claude 或 ~/.codex，请用 --target 明确指定（可先创建对应目录）。")
    if target_arg == "both":
        return ["claude", "codex"], "both"
    if target_arg in known:
        return [target_arg], target_arg
    die(f"未知 --target: {target_arg}")

def skill_dirs(repo):
    src = repo / "skills"
    return sorted(d for d in src.iterdir() if d.is_dir()) if src.is_dir() else []

def load_block(repo):
    text = read_utf8(repo / "AGENTS.md")
    if text.count(BEGIN_MARK) != 1 or text.count(END_MARK) != 1:
        die("源 AGENTS.md 的受管标记不成对")
    b, e = text.index(BEGIN_MARK), text.index(END_MARK) + len(END_MARK)
    return text, text[b:e]

def marker_stats(text):
    tb, te = text.count(BEGIN_MARK), text.count(END_MARK)
    exact = lambda m: sum(1 for ln in text.splitlines() if ln.strip() == m)
    return tb, te, exact(BEGIN_MARK), exact(END_MARK)

def try_link(src, tgt, is_dir):
    """优先 symlink，Windows 目录降级 junction；失败返回 None。"""
    tgt.parent.mkdir(parents=True, exist_ok=True)
    if tgt.is_symlink() or (is_dir and tgt.exists() and points_to(tgt, src)):
        return tgt if points_to(tgt, src) else None
    if tgt.exists():
        return None
    try:
        os.symlink(str(Path(src).resolve()), str(tgt), target_is_directory=is_dir)
        return tgt
    except OSError:
        pass
    if os.name == "nt" and is_dir:
        try:
            import _winapi
            _winapi.CreateJunction(str(Path(src).resolve()), str(tgt))
            return tgt
        except (OSError, ImportError):
            return None
    return None

def plan_rules(mf, key, home, mode, repo, ts):
    """返回 (status, target, backup, reason)。"""
    src_text, src_block = load_block(repo)
    tgt = mf.rules_path(key, home)
    if points_to(tgt, repo / "AGENTS.md"):
        return "skip", tgt, None, "链接已指向仓库源"
    if tgt.is_symlink():
        return "error", tgt, None, "目标是符号链接，拒绝写入（人工处理）"
    if not tgt.exists():
        return "new", tgt, None, "新建"
    raw = tgt.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "error", tgt, None, "无法按 UTF-8 解码，请先转 UTF-8"
    tb, te, xb, xe = marker_stats(text)
    if tb == 0 and te == 0:
        if mode == "abort":
            return "abort", tgt, None, "已有内容但没有受管标记"
        bak = make_backup(mf.backup_root(home), tgt, ts, dry_run=True)
        if mode == "replace":
            return "replace_file", tgt, bak, "整文件替换"
        reason = "追加受管区块"
        if "全局核心铁律" in text or "不可逆操作确认" in text:
            reason += "；[警告] 疑似已有旧版未受管铁律，直接追加会重复或冲突，" \
                      "请人工合并，或经用户确认后改用 --mode replace"
        return "append", tgt, bak if "警告" in reason else None, reason
    if tb != 1 or te != 1 or xb != 1 or xe != 1:
        return "error", tgt, None, "标记异常：受管标记须各出现恰好一次且独占一行"
    if not text.strip():
        return ("replace_file", tgt, make_backup(mf.backup_root(home), tgt, ts, dry_run=True), "仅含空白")
    old = text[text.index(BEGIN_MARK):text.index(END_MARK) + len(END_MARK)]
    if norm_text(old) == norm_text(src_block):
        if raw[:3] == b"\xef\xbb\xbf":
            return "replace_block", tgt, None, "已最新，仅剥离 BOM"
        return "skip", tgt, None, "跳过：已最新"
    bak = make_backup(mf.backup_root(home), tgt, ts, dry_run=True)
    return "replace_block", tgt, bak, "替换受管区块"

def rebuild_rules(tgt, src_block, eol):
    """替换目标文件 BEGIN..END 区块，保留其余内容与换行风格。"""
    text = read_utf8(tgt)
    body = (text[:text.index(BEGIN_MARK)] + src_block
            + text[text.index(END_MARK) + len(END_MARK):])
    atomic_write(tgt, body.replace("\r\n", "\n").replace("\n", eol))

def apply_rules(mf, key, home, mode, repo, ts, dry_run):
    st, tgt, bak, reason = plan_rules(mf, key, home, mode, repo, ts)
    if st == "error":
        die(reason)
    if st == "abort":
        die(f"{tgt} 已有内容但没有受管标记；按 --mode abort 停止")
    if st == "skip":
        print("  规则文件: 跳过：已最新")
        return
    label = {"new": "新建", "append": "追加受管区块", "replace_block": "替换受管区块",
             "replace_file": "整文件替换"}[st]
    if dry_run:
        suffix = f"；{reason}" if reason.startswith("追加") and "警告" in reason else ""
        print(f"  规则文件: {label}{suffix}（{tgt}）")
        if bak:
            print(f"    备份 -> {bak}")
        return
    if st == "replace_block" and reason.startswith("已最新"):
        _, src_block = load_block(repo)
        rebuild_rules(tgt, src_block, detect_eol(read_utf8(tgt)))
        print("  规则文件: 已最新，仅剥离 BOM")
        return
    if bak:
        make_backup(mf.backup_root(home), tgt, ts)
        print(f"    备份 -> {bak}")
    src_text, src_block = load_block(repo)
    if st in ("new", "replace_file"):
        atomic_write(tgt, src_text.replace("\r\n", "\n"))
    elif st == "append":
        text = read_utf8(tgt)
        eol = detect_eol(text)
        base = norm_text(text)
        if base and not base.endswith("\n"):
            base += "\n"
        body = (base + "\n" + norm_text(src_block) + "\n").replace("\n", eol)
        atomic_write(tgt, body)
    else:
        rebuild_rules(tgt, src_block, detect_eol(read_utf8(tgt)))
    suffix = f"；{reason}" if reason.startswith("追加") and "警告" in reason else ""
    print(f"  规则文件: {label}{suffix}（{tgt}）")

def apply_skills(mf, key, home, mode, repo, ts, dry_run):
    hs = mf.skills_dir(key, home)
    for sd in skill_dirs(repo):
        tgt_dir, tgt_skill = hs / sd.name, hs / sd.name / "SKILL.md"
        if mode == "link":
            lk = try_link(sd, tgt_dir, is_dir=True)
            if lk is not None:
                print(f"  Skill {sd.name}: 链接 -> {sd}")
                continue
            print(f"  Skill {sd.name}: 链接失败，降级 Copy Mode")
        if tgt_dir.is_symlink():
            print(f"  Skill {sd.name}: 目标已是符号链接，跳过（人工处理）")
            continue
        if tgt_skill.exists():
            old, new = read_utf8(tgt_skill), read_utf8(sd / "SKILL.md")
            if norm_text(old) == norm_text(new):
                extras = sorted(set(os.listdir(tgt_dir)) - {"SKILL.md"})
                if extras:
                    print(f"  Skill {sd.name}: 目录内其他文件不动（{', '.join(extras[:3])}…）")
                continue
            bak = make_backup(mf.backup_root(home), tgt_skill, ts, dry_run=dry_run)
            if not dry_run:
                atomic_write(tgt_skill, norm_text(new).replace("\n", detect_eol(old)))
            print(f"  Skill {sd.name}: {'将' if dry_run else ''}覆盖（备份 -> {bak}）")
        else:
            if not dry_run:
                shutil.copytree(sd, tgt_dir)
            print(f"  Skill {sd.name}: 新建")
    repo_names = {d.name for d in skill_dirs(repo)}
    others = []
    if hs.is_dir():
        for d in hs.iterdir():
            try:
                if d.is_dir() and d.name not in repo_names:
                    others.append(d.name)
            except OSError:  # 断链/无权限的符号链接
                continue
        others = sorted(others)
    if others:
        pairs = [f"{o} ≈ {mf.overlaps[o]}" if o in mf.overlaps else o for o in others]
        print(f"  现有其他 Skill（仅提醒，不删除）: {', '.join(pairs)}")

def apply_prompts(mf, key, home, repo, dry_run):
    pd = mf.prompts_dir(key, home)
    if not pd or key != "codex":
        return
    for f in sorted((repo / "prompts").glob("*.md")) if (repo / "prompts").is_dir() else []:
        tgt = pd / f.name
        if tgt.exists() and norm_text(read_utf8(tgt)) == norm_text(read_utf8(f)):
            continue
        if not dry_run:
            atomic_write(tgt, norm_text(read_utf8(f)))
        print(f"  Prompt {f.name}: {'新建' if not tgt.exists() else '覆盖'} -> {pd}")

def state_file(repo):
    return repo / STATE_FILE

def load_state(repo):
    try:
        return json.loads(state_file(repo).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

def save_state(repo, st):
    atomic_write(state_file(repo), json.dumps(st, ensure_ascii=False, indent=2) + "\n")

def cmd_setup(args):
    mf = Manifest(REPO)
    home = home_base(args.home)
    targets, label = resolve_targets(args.target, mf, home)
    mode = args.mode or mf.default_mode
    print(f"agent-config {VERSION} setup（mode={mode}）\n宿主: {label}\n备份根目录: {mf.backup_root(home)}")
    ts = ts_now()
    if args.dry_run:
        print("[dry-run] 以下为计划，未写入任何配置文件。")
    for key in targets:
        print(f"[{key}]")
        apply_rules(mf, key, home, mode, REPO, ts, args.dry_run)
        apply_skills(mf, key, home, mode, REPO, ts, args.dry_run)
        apply_prompts(mf, key, home, REPO, args.dry_run)
    if not args.dry_run:
        st = load_state(REPO)
        st.setdefault("rules", {}).update(
            {k: sha256_norm(mf.rules_path(k, home)) for k in targets})
        save_state(REPO, st)
        print(f"\n下一步: python scripts/agent_sync.py doctor --target {args.target}")
    else:
        print("确认后去掉 --dry-run 执行。")

def verify_content(tgt, src):
    """对齐原 v2.2.0 --verify：受管区块逐字一致 + 铁律编号 1-10。"""
    try:
        t, s = read_utf8(tgt), read_utf8(src)
    except SystemExit:
        return False
    if t.count(BEGIN_MARK) != 1 or t.count(END_MARK) != 1:
        return False
    b, e = t.index(BEGIN_MARK), t.index(END_MARK) + len(END_MARK)
    block = t[b:e]
    b2, e2 = s.index(BEGIN_MARK), s.index(END_MARK) + len(END_MARK)
    if norm_text(block) != norm_text(s[b2:e2]):
        return False
    nums = sorted({int(m.group(1)) for m in re.finditer(r"(?m)^(\d+)\. \*\*", block)})
    return nums == list(range(1, 11))

def cmd_doctor(args):
    mf = Manifest(REPO)
    home = home_base(args.home)
    targets, _ = resolve_targets(args.target, mf, home)
    st = load_state(REPO)
    issues = []
    for key in targets:
        tgt, src = mf.rules_path(key, home), REPO / "AGENTS.md"
        if points_to(tgt, src):
            print(f"[{key}] 规则文件: 链接健康")
        elif not tgt.exists():
            issues.append(f"[{key}] 规则文件缺失: {tgt}")
        elif not verify_content(tgt, src):
            issues.append(f"[{key}] 规则文件内容与仓库不一致（受管区块/铁律 1-10/UTF-8）")
        else:
            print(f"[{key}] 规则文件: 一致（受管区块）")
        hs = mf.skills_dir(key, home)
        for sd in skill_dirs(REPO):
            tp = hs / sd.name / "SKILL.md"
            if not tp.exists():
                issues.append(f"[{key}] Skill 缺失: {sd.name}")
            elif sha256_norm(tp) != sha256_norm(sd / "SKILL.md"):
                issues.append(f"[{key}] Skill 与仓库不一致: {sd.name}")
    if issues:
        for i in issues:
            print(f"[警告] {i}")
        sys.exit(2)
    print("doctor: 全部健康")

def cmd_sync_back(args):
    mf = Manifest(REPO)
    home = home_base(args.home)
    targets, _ = resolve_targets(args.target, mf, home)
    st = load_state(REPO)
    conflicts = []
    for key in targets:
        tgt, src = mf.rules_path(key, home), REPO / "AGENTS.md"
        if not tgt.exists():
            continue
        local, repo_h = sha256_norm(tgt), sha256_norm(src)
        base = st.get("rules", {}).get(key)
        if local == repo_h:
            continue
        if base and local != base and repo_h != base:
            conflicts.append((key, str(tgt)))
            continue
        if args.dry_run:
            print(f"[{key}] 将写回规则文件改动（dry-run）")
            continue
        text = read_utf8(tgt)
        eol = detect_eol(read_utf8(src))
        atomic_write(src, norm_text(text).replace("\n", eol))
        print(f"[{key}] 已写回规则文件改动")
    if conflicts:
        for key, p in conflicts:
            print(f"[阻断] {key}: 宿主与仓库双端均改动，请人工合并: {p}")
        sys.exit(2)

def audit_repo(repo):
    findings = []
    try:
        r = subprocess.run(["git", "diff", "--name-only", "--cached", "--diff-filter=ACMR"],
                           capture_output=True, cwd=repo, timeout=30)
        changed = [ln for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
        if not changed:
            r = subprocess.run(["git", "status", "--porcelain", "-uno"],
                               capture_output=True, cwd=repo, timeout=30)
            changed = [ln[3:] for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    except (OSError, subprocess.TimeoutExpired):
        changed = []
    if changed:
        files = [repo / c for c in changed if (repo / c).is_file()]
    else:
        files = [p for p in repo.rglob("*") if p.is_file()
                 and not (AUDIT_EXCLUDE_DIRS & set(p.parts))]
    for p in files:
        if p.suffix.lower() not in AUDIT_TEXT_SUFFIXES or p.name in (STATE_FILE, 'REFACTOR_PLAN.md'):
            continue
        try:
            text = Path(p).read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            findings.append(f"{p.relative_to(repo).as_posix()}: 非 UTF-8 文本")
            continue
        rel = p.relative_to(repo).as_posix()
        for pat, name in SECRET_PATTERNS:
            findings += [f"{rel}: 疑似{name}（{m.group(0)[:24]}…）" for m in pat.finditer(text)]
        findings += [f"{rel}: 疑似硬编码本地路径（{m.group(0)}）"
                     for pat in PATH_PATTERNS for m in pat.finditer(text)]
    for sd in skill_dirs(repo):
        skill = sd / "SKILL.md"
        if not skill.exists():
            findings.append(f"skills/{sd.name}/: 缺少 SKILL.md")
            continue
        text = read_utf8(skill)
        if not re.search(r"(?m)^name:\s*\S+", text):
            findings.append(f"skills/{sd.name}/SKILL.md: 缺 frontmatter name")
        if not re.search(r"(?m)^description:\s*\S+", text):
            findings.append(f"skills/{sd.name}/SKILL.md: 缺 frontmatter description")
        if len(text.encode("utf-8")) > SKILL_SIZE_WARN:
            print(f"[提示] skills/{sd.name}/SKILL.md 超过 {SKILL_SIZE_WARN} 字节，建议拆层")
    return findings

def cmd_audit(args):
    print(f"audit: 扫描仓库（REPO={REPO}）")
    findings = audit_repo(REPO)
    if findings:
        for f in findings:
            print(f"[FAIL] {f}")
        sys.exit(2)
    print("audit: 未发现密钥、硬编码本地路径或 frontmatter 缺失")

def cmd_status(args):
    mf = Manifest(REPO)
    home = home_base(args.home)
    out = {"version": VERSION, "mode": mf.default_mode,
           "state_file": str(state_file(REPO)), "hosts": {}}
    for key in mf.hosts:
        root = expand_user(mf.hosts[key]["root"], home)
        out["hosts"][key] = {"root": str(root),
                             "rules_exists": mf.rules_path(key, home).exists(),
                             "skills": [d.name for d in skill_dirs(REPO)]}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"agent-config {VERSION}（mode={mf.default_mode}）")
        for key, v in out["hosts"].items():
            print(f"{key}: rules={'有' if v['rules_exists'] else '无'} "
                  f"skills={len(v['skills'])} root={v['root']}")

def main(argv=None):
    ap = argparse.ArgumentParser(prog="agent_sync", description="agent-config 同步引擎")
    ap.add_argument("--version", action="version", version=f"agent-config {VERSION}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="覆盖仓库根（测试沙盒用）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def sp(name, **kw):
        p = sub.add_parser(name, parents=[common], **kw)
        p.add_argument("--target", default="auto")
        p.add_argument("--home")
        return p
    p = sp("setup", help="一键初始化/恢复")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--mode", choices=["append", "replace", "abort", "copy", "link"])
    p.set_defaults(func=cmd_setup)
    p = sp("doctor", help="健康体检与断链自愈")
    p.set_defaults(func=cmd_doctor)
    p = sp("sync-back", help="Copy Mode 反向采集")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_sync_back)
    p = sub.add_parser("audit", parents=[common], help="安全与规范门禁")
    p.set_defaults(func=cmd_audit)
    p = sub.add_parser("status", parents=[common], help="状态摘要")
    p.add_argument("--json", action="store_true")
    p.add_argument("--home")
    p.set_defaults(func=cmd_status)
    args = ap.parse_args(argv)
    if getattr(args, "repo", None):
        global REPO
        REPO = Path(args.repo).resolve()
    args.func(args)


if __name__ == "__main__":
    main()
