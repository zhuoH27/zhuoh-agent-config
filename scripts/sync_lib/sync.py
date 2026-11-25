# -*- coding: utf-8 -*-
"""规则同步、技能同步、提示词同步、健康体检与状态统计。"""
import json
import re
import shutil
import sys

from sync_lib.core import (
    BEGIN_MARK,
    END_MARK,
    VERSION,
    Manifest,
    atomic_write,
    detect_eol,
    die,
    home_base,
    is_link,
    make_backup,
    norm_text,
    points_to,
    read_utf8,
    resolve_targets,
    sha256_norm,
    sha256_raw,
    skill_dirs,
    try_link,
    ts_now,
)


def marker_stats(text):
    tb, te = text.count(BEGIN_MARK), text.count(END_MARK)
    exact = lambda m: sum(1 for ln in text.splitlines() if ln.strip() == m)
    ordered = (tb == 1 and te == 1 and text.index(BEGIN_MARK) < text.index(END_MARK))
    return tb, te, exact(BEGIN_MARK), exact(END_MARK), ordered


def load_block(repo, rules_rel="AGENTS.md"):
    text = read_utf8(repo / rules_rel)
    tb, te, xb, xe, ordered = marker_stats(text)
    if tb != 1 or te != 1 or xb != 1 or xe != 1 or not ordered:
        die("源 AGENTS.md 的受管标记异常（须成对、独占一行且 BEGIN 在 END 之前）")
    b, e = text.index(BEGIN_MARK), text.index(END_MARK) + len(END_MARK)
    return text, text[b:e]


def plan_rules(mf, key, home, mode, repo, ts, planned=None):
    """返回 (status, target, backup, reason)。"""
    _, src_block = load_block(repo, mf.rules_src)
    tgt = mf.rules_path(key, home)
    host_root = mf.host_root(key, home)
    if points_to(tgt, repo / mf.rules_src):
        return "skip", tgt, None, "跳过：链接已指向仓库源"
    if is_link(tgt):
        return "error", tgt, None, "目标是符号链接，拒绝写入（人工处理）"
    if not tgt.exists():
        return "new", tgt, None, "新建"
    raw = tgt.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "error", tgt, None, "无法按 UTF-8 解码，请先转 UTF-8"

    tb, te, xb, xe, ordered = marker_stats(text)
    if tb == 0 and te == 0:
        if mode == "abort":
            return "abort", tgt, None, "已有内容但没有受管标记"
        bak = make_backup(
            mf.backup_root(home), tgt, ts,
            host_key=key, host_root=host_root, dry_run=True, planned=planned,
        )
        if mode == "replace":
            return "replace_file", tgt, bak, "整文件替换"
        reason = "追加受管区块"
        if "全局核心铁律" in text or "不可逆操作确认" in text:
            reason += (
                "；[警告] 疑似已有旧版未受管铁律，直接追加会重复或冲突，"
                "请人工合并，或经用户确认后改用 --mode replace"
            )
        return "append", tgt, bak, reason

    if tb != 1 or te != 1 or xb != 1 or xe != 1 or not ordered:
        return "error", tgt, None, "标记异常：受管标记须各出现恰好一次、独占一行且 BEGIN 在 END 之前"

    old = text[text.index(BEGIN_MARK):text.index(END_MARK) + len(END_MARK)]
    if norm_text(old) == norm_text(src_block):
        if raw[:3] == b"\xef\xbb\xbf":
            bak = make_backup(
                mf.backup_root(home), tgt, ts,
                host_key=key, host_root=host_root, dry_run=True, planned=planned,
            )
            return "replace_block", tgt, bak, "已最新，仅剥离 BOM"
        return "skip", tgt, None, "跳过：已最新"

    bak = make_backup(
        mf.backup_root(home), tgt, ts,
        host_key=key, host_root=host_root, dry_run=True, planned=planned,
    )
    return "replace_block", tgt, bak, "替换受管区块"


def rebuild_rules(tgt, src_block, eol):
    """替换目标文件 BEGIN..END 区块，保留其余内容与换行风格。"""
    text = read_utf8(tgt)
    body = (
        text[:text.index(BEGIN_MARK)]
        + src_block
        + text[text.index(END_MARK) + len(END_MARK):]
    )
    atomic_write(tgt, body.replace("\r\n", "\n").replace("\n", eol))


def apply_rules(mf, key, home, mode, repo, ts, dry_run, planned=None):
    st, tgt, bak, reason = plan_rules(mf, key, home, mode, repo, ts, planned=planned if dry_run else None)
    if st == "error":
        die(reason)
    if st == "abort":
        die(f"{tgt} 已有内容但没有受管标记；按 --mode abort 停止")
    if st == "skip":
        print(f"  规则文件: {reason}")
        return

    label = {
        "new": "新建",
        "append": "追加受管区块",
        "replace_block": "替换受管区块",
        "replace_file": "整文件替换",
    }[st]
    suffix = f"；{reason.split('；', 1)[1]}" if reason.startswith("追加") and "警告" in reason else ""

    if dry_run:
        print(f"  规则文件: {label}{suffix}（{tgt}）")
        if bak:
            print(f"    备份 -> {bak}")
        return

    if bak:
        real_bak = make_backup(
            mf.backup_root(home), tgt, ts,
            host_key=key, host_root=mf.host_root(key, home), dry_run=False,
        )
        print(f"    备份 -> {real_bak}")

    src_text, src_block = load_block(repo, mf.rules_src)
    if st == "replace_block" and reason.startswith("已最新"):
        rebuild_rules(tgt, src_block, detect_eol(read_utf8(tgt)))
        print("  规则文件: 已最新，仅剥离 BOM")
        return
    if st in ("new", "replace_file"):
        atomic_write(tgt, src_text.replace("\r\n", "\n"))
    elif st == "append":
        text = read_utf8(tgt)
        eol = detect_eol(text)
        base = norm_text(text)
        if base:
            if not base.endswith("\n"):
                base += "\n"
            body = (base + "\n" + norm_text(src_block) + "\n").replace("\n", eol)
        else:
            body = (norm_text(src_block) + "\n").replace("\n", eol)
        atomic_write(tgt, body)
    else:
        rebuild_rules(tgt, src_block, detect_eol(read_utf8(tgt)))
    print(f"  规则文件: {label}{suffix}（{tgt}）")


def _sync_skill_file(src_file, tgt_file, bak_root, host_key, host_root, ts,
                     dry_run, sd_name, rel_str, planned=None):
    is_md = src_file.suffix.lower() == ".md"
    if tgt_file.exists():
        if is_md:
            old, new = read_utf8(tgt_file), read_utf8(src_file)
            if norm_text(old) == norm_text(new):
                return
            payload = norm_text(new).replace("\n", detect_eol(old))
        else:
            if tgt_file.read_bytes() == src_file.read_bytes():
                return
            payload = src_file.read_bytes()
        bak = make_backup(
            bak_root, tgt_file, ts,
            host_key=host_key, host_root=host_root, dry_run=dry_run,
            planned=planned if dry_run else None,
        )
        if not dry_run:
            atomic_write(tgt_file, payload)
        print(f"  Skill {sd_name} ({rel_str}): {'将' if dry_run else ''}覆盖（备份 -> {bak}）")
    else:
        if not dry_run:
            payload = norm_text(read_utf8(src_file)) if is_md else src_file.read_bytes()
            atomic_write(tgt_file, payload)
        print(f"  Skill {sd_name} ({rel_str}): {'将' if dry_run else ''}新增")


def apply_skills(mf, key, home, skill_mode, repo, ts, dry_run, planned=None):
    hs = mf.skills_dir(key, home)
    if is_link(hs):
        print(f"  Skills: 根目录是链接（{hs}），跳过（人工处理）")
        return
    bak_root = mf.backup_root(home)
    host_root = mf.host_root(key, home)
    for sd in skill_dirs(repo, mf.skills_src):
        tgt_dir = hs / sd.name
        if skill_mode == "link":
            if dry_run:
                if points_to(tgt_dir, sd):
                    print(f"  Skill {sd.name}: 跳过（链接已指向仓库源）")
                    continue
                if not tgt_dir.exists() and not is_link(tgt_dir):
                    print(f"  Skill {sd.name}: 将链接 -> {sd}")
                    continue
                print(f"  Skill {sd.name}: 目标已存在，将降级 Copy Mode")
            else:
                lk = try_link(sd, tgt_dir, is_dir=True)
                if lk is not None:
                    print(f"  Skill {sd.name}: 链接 -> {sd}")
                    continue
                print(f"  Skill {sd.name}: 链接失败，降级 Copy Mode")
        if is_link(tgt_dir):
            print(f"  Skill {sd.name}: 目标已是链接，跳过（人工处理）")
            continue
        if not tgt_dir.exists():
            if not dry_run:
                shutil.copytree(sd, tgt_dir)
            print(f"  Skill {sd.name}: {'将' if dry_run else ''}新建")
            continue
        for src_file in sorted(p for p in sd.rglob("*") if p.is_file()):
            rel = src_file.relative_to(sd)
            walk = tgt_dir
            blocked = False
            for part in rel.parts[:-1]:
                walk = walk / part
                if is_link(walk):
                    print(f"  Skill {sd.name} ({rel.as_posix()}): 中间目录是链接，跳过（人工处理）")
                    blocked = True
                    break
            if blocked:
                continue
            _sync_skill_file(
                src_file, tgt_dir / rel, bak_root, key, host_root, ts,
                dry_run, sd.name, rel.as_posix(), planned=planned,
            )
        extras = sorted(
            p.relative_to(tgt_dir).as_posix()
            for p in tgt_dir.rglob("*")
            if p.is_file() and not (sd / p.relative_to(tgt_dir)).exists()
        )
        if extras:
            print(f"  Skill {sd.name}: 目录内其他文件不动（{', '.join(extras[:3])}…）")

    repo_names = {d.name for d in skill_dirs(repo, mf.skills_src)}
    others = []
    if hs.is_dir():
        for d in hs.iterdir():
            try:
                if d.is_dir() and d.name not in repo_names:
                    others.append(d.name)
            except OSError:
                continue
        others.sort()
    if others:
        pairs = [f"{o} ≈ {mf.overlaps[o]}" if o in mf.overlaps else o for o in others]
        print(f"  现有其他 Skill（仅提醒，不删除）: {', '.join(pairs)}")


def apply_prompts(mf, key, home, repo, ts, dry_run, planned=None):
    pd = mf.prompts_dir(key, home)
    if not pd:
        return
    if is_link(pd):
        print(f"  Prompt: 目标目录是符号链接，跳过（人工处理）")
        return
    host_root = mf.host_root(key, home)
    src_dir = repo / mf.prompts_src
    for f in sorted(src_dir.glob("*.md")) if src_dir.is_dir() else []:
        tgt = pd / f.name
        existed = tgt.exists()
        new_text = norm_text(read_utf8(f))
        if existed:
            old_text = read_utf8(tgt)
            if norm_text(old_text) == new_text:
                continue
            eol = detect_eol(old_text)
            bak = make_backup(
                mf.backup_root(home), tgt, ts,
                host_key=key, host_root=host_root, dry_run=dry_run,
                planned=planned if dry_run else None,
            )
        else:
            eol, bak = "\n", None
        if not dry_run:
            atomic_write(tgt, new_text.replace("\n", eol))
        action = ("将覆盖" if dry_run else "覆盖") if existed else ("将新建" if dry_run else "新建")
        print(f"  Prompt {f.name}: {action} -> {pd}" + (f"（备份 -> {bak}）" if bak else ""))


def cmd_setup(args, repo):
    mf = Manifest(repo)
    home = home_base(args.home)
    targets, label = resolve_targets(args.target, mf, home)
    rules_mode = args.mode or "append"
    skill_mode = args.skill_mode or mf.default_mode
    print(
        f"agent-config {VERSION} setup（rules_mode={rules_mode}, skill_mode={skill_mode}）\n"
        f"宿主: {label}\n备份根目录: {mf.backup_root(home)}"
    )
    ts = ts_now()
    planned = set() if args.dry_run else None
    if args.dry_run:
        print("[dry-run] 以下为计划，未写入任何配置文件。")
    for key in targets:
        print(f"[{key}]")
        apply_rules(mf, key, home, rules_mode, repo, ts, args.dry_run, planned=planned)
        apply_skills(mf, key, home, skill_mode, repo, ts, args.dry_run, planned=planned)
        apply_prompts(mf, key, home, repo, ts, args.dry_run, planned=planned)
    if not args.dry_run:
        print(f"\n下一步: python scripts/agent_sync.py doctor --target {args.target}")
    else:
        print("确认后去掉 --dry-run 执行。")


def verify_content(tgt, src):
    """受管区块逐字一致 + 标记顺序正确 + 铁律编号 1-10。"""
    try:
        t, s = read_utf8(tgt), read_utf8(src)
    except SystemExit:
        return False
    tb, te, xb, xe, ordered = marker_stats(t)
    if tb != 1 or te != 1 or xb != 1 or xe != 1 or not ordered:
        return False
    sb, se, sxb, sxe, sordered = marker_stats(s)
    if sb != 1 or se != 1 or sxb != 1 or sxe != 1 or not sordered:
        return False
    block = t[t.index(BEGIN_MARK):t.index(END_MARK) + len(END_MARK)]
    src_block = s[s.index(BEGIN_MARK):s.index(END_MARK) + len(END_MARK)]
    if norm_text(block) != norm_text(src_block):
        return False
    nums = sorted({int(m.group(1)) for m in re.finditer(r"(?m)^(\d+)\. \*\*", block)})
    return nums == list(range(1, 11))


def cmd_doctor(args, repo):
    mf = Manifest(repo)
    home = home_base(args.home)
    targets, _ = resolve_targets(args.target, mf, home)
    issues = []
    for key in targets:
        tgt, src = mf.rules_path(key, home), repo / mf.rules_src
        if points_to(tgt, src):
            print(f"[{key}] 规则文件: 链接健康")
        elif not tgt.exists():
            issues.append(f"[{key}] 规则文件缺失: {tgt}")
        elif not verify_content(tgt, src):
            issues.append(f"[{key}] 规则文件内容与仓库不一致（受管区块/铁律 1-10/UTF-8）")
        else:
            print(f"[{key}] 规则文件: 一致（受管区块）")

        hs = mf.skills_dir(key, home)
        for sd in skill_dirs(repo, mf.skills_src):
            for sf in sorted(p for p in sd.rglob("*") if p.is_file()):
                rel = sf.relative_to(sd)
                tp = hs / sd.name / rel
                if not tp.exists():
                    issues.append(f"[{key}] Skill 文件缺失: {sd.name}/{rel.as_posix()}")
                    continue
                same = (
                    (sha256_norm(tp) == sha256_norm(sf))
                    if sf.suffix.lower() == ".md"
                    else (sha256_raw(tp) == sha256_raw(sf))
                )
                if not same:
                    issues.append(f"[{key}] Skill 与仓库不一致: {sd.name}/{rel.as_posix()}")

        pd = mf.prompts_dir(key, home)
        if pd:
            src_prompts = repo / mf.prompts_src
            for pf in sorted(src_prompts.glob("*.md")) if src_prompts.is_dir() else []:
                tp = pd / pf.name
                if not tp.exists():
                    issues.append(f"[{key}] Prompt 缺失: {pf.name}")
                elif sha256_norm(tp) != sha256_norm(pf):
                    issues.append(f"[{key}] Prompt 与仓库不一致: {pf.name}")

    if issues:
        for i in issues:
            print(f"[警告] {i}")
        sys.exit(2)
    print("doctor: 全部健康")


def cmd_status(args, repo):
    mf = Manifest(repo)
    home = home_base(args.home)
    repo_skills = [d.name for d in skill_dirs(repo, mf.skills_src)]
    out = {"version": VERSION, "mode": mf.default_mode, "skills_expected": len(repo_skills), "hosts": {}}
    for key in mf.hosts:
        root = mf.host_root(key, home)
        hs = mf.skills_dir(key, home)
        installed_skills = [
            name for name in repo_skills if (hs / name / "SKILL.md").exists()
        ]
        host_info = {
            "root": str(root),
            "rules_exists": mf.rules_path(key, home).exists(),
            "skills": installed_skills,
        }
        pd = mf.prompts_dir(key, home)
        if pd:
            src_prompts = repo / mf.prompts_src
            expected_prompts = [p.name for p in sorted(src_prompts.glob("*.md"))] if src_prompts.is_dir() else []
            host_info["prompts"] = [name for name in expected_prompts if (pd / name).exists()]
        out["hosts"][key] = host_info

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"agent-config {VERSION}（skill_mode={mf.default_mode}）")
        for key, v in out["hosts"].items():
            extra = f" prompts={len(v['prompts'])}" if "prompts" in v else ""
            print(
                f"{key}: rules={'有' if v['rules_exists'] else '无'} "
                f"skills={len(v['skills'])}/{len(repo_skills)}{extra} root={v['root']}"
            )
