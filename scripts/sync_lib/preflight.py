# -*- coding: utf-8 -*-
"""setup 前置校验：任何写入前对全部 target 做只读预检。

收集所有硬阻塞项后一次性报告并退出（exit 1），保证零写入；
dry-run 与 apply 共用本模块，dry-run 计划不会漏报。
"""
import sys
from pathlib import Path

from sync_lib.core import (
    BEGIN_MARK,
    END_MARK,
    Manifest,
    is_link,
    marker_pair_ok,
    skill_dirs,
)


def _rules_ok(tgt):
    """规则目标可处理：不存在/是健康链接/标记正常的 UTF-8 文本。"""
    if not tgt.exists():
        return None
    if is_link(tgt):
        return "规则文件是链接（非指向仓库源），拒绝写入"
    try:
        raw = tgt.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return "无法按 UTF-8 解码"
    tb, te = text.count(BEGIN_MARK), text.count(END_MARK)
    if tb == 0 and te == 0:
        return None  # 无标记：append/replace/abort 三模式均可处理，不是 preflight 硬错误
    if not marker_pair_ok(text):
        return "标记异常（须成对且 BEGIN 在 END 之前）"
    return None


def collect(mf, targets, home, repo):
    """返回硬阻塞项列表；空列表 = 可以继续。"""
    issues = []
    for key in targets:
        host_root = mf.host_root(key, home)
        rules = mf.rules_path(key, home)
        err = _rules_ok(rules)
        if err:
            issues.append(f"[{key}] 规则文件 {rules}: {err}")

        hs = mf.skills_dir(key, home)
        if is_link(hs):
            pass  # apply_skills 自身会跳过并提示，不属硬阻塞
        elif hs.exists() and not hs.is_dir():
            issues.append(f"[{key}] skills 路径 {hs} 存在且不是目录")
        for sd in skill_dirs(repo, mf.skills_src):
            tgt_dir = hs / sd.name
            if tgt_dir.is_symlink():
                continue  # 链接由 apply_skills 的三分法处理
            if tgt_dir.exists() and not tgt_dir.is_dir():
                issues.append(f"[{key}] 技能目标 {tgt_dir} 存在且不是目录")

        pd = mf.prompts_dir(key, home)
        if pd and pd.exists() and not pd.is_dir():
            issues.append(f"[{key}] prompts 路径 {pd} 存在且不是目录")
    return issues


def check_or_die(mf, targets, home, repo):
    issues = collect(mf, targets, home, repo)
    if issues:
        print("preflight: 发现以下阻塞项，未写入任何文件：", file=sys.stderr)
        for i in issues:
            print(f"  [阻塞] {i}", file=sys.stderr)
        sys.exit(1)
    return issues
