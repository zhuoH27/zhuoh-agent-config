# -*- coding: utf-8 -*-
"""仓库推送前安全与规范门禁（密钥、硬编码路径、UTF-8、Skill frontmatter）。"""
import fnmatch
import json
import re
import sys
from pathlib import Path

from sync_lib.core import read_utf8, skill_dirs

SKILL_SIZE_WARN = 10 * 1024
AUDIT_EXCLUDE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", "_backup", "node_modules", "tests", "_t*",
}
AUDIT_TEXT_SUFFIXES = {
    ".md", ".py", ".json", ".yml", ".yaml", ".ps1", ".txt",
    ".toml", ".cfg", ".ini", ".html", ".css", ".js", ".ts",
}
SECRET_PATTERNS = tuple((re.compile(p), n) for p, n in (
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI 风格 API Key"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"xox[bapr]-[A-Za-z0-9-]{10,}", "Slack Token"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "私钥"),
    (r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_.-]{16,}['\"]", "API Key 赋值"),
    (r"(?i)(?:secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_.-]{16,}['\"]", "凭据赋值"),
))
PATH_PATTERNS = tuple(re.compile(p) for p in (
    r"[A-Za-z]:\\Users\\[^\s\"'`]+",
    r"[A-Za-z]:/Users/",
    r"(?<![\w/])/Users/[A-Za-z0-9_-]+/",
    r"(?<![\w/])/home/[A-Za-z0-9_-]+/",
))


def audit_repo(repo):
    repo = Path(repo)
    findings = []
    mf_path = repo / "manifest.json"
    skills_rel = "skills"
    if mf_path.is_file():
        try:
            skills_rel = json.loads(mf_path.read_text(encoding="utf-8")).get("sources", {}).get("skills", "skills")
        except (OSError, json.JSONDecodeError):
            pass

    files = [p for p in repo.rglob("*") if p.is_file()]
    files = [
        p for p in files
        if not any(
            fnmatch.fnmatchcase(part, pat)
            for part in p.relative_to(repo).parts[:-1]
            for pat in AUDIT_EXCLUDE_DIRS
        )
    ]

    for p in files:
        if p.suffix.lower() not in AUDIT_TEXT_SUFFIXES or p.name == "REFACTOR_PLAN.md":
            continue
        rel = p.relative_to(repo).as_posix()
        try:
            text = p.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            findings.append(f"{rel}: 非 UTF-8 文本")
            continue
        for pat, name in SECRET_PATTERNS:
            findings.extend(f"{rel}: 疑似{name}（{m.group(0)[:24]}…）" for m in pat.finditer(text))
        findings.extend(
            f"{rel}: 疑似硬编码本地路径（{m.group(0)}）"
            for pat in PATH_PATTERNS for m in pat.finditer(text)
        )

    for sd in skill_dirs(repo, skills_rel):
        skill = sd / "SKILL.md"
        if not skill.exists():
            findings.append(f"{skills_rel}/{sd.name}/: 缺少 SKILL.md")
            continue
        text = read_utf8(skill)
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            findings.append(f"{skills_rel}/{sd.name}/SKILL.md: 首行缺少 frontmatter 起始标记 ---")
        elif not any(ln.strip() == "---" for ln in lines[1:]):
            findings.append(f"{skills_rel}/{sd.name}/SKILL.md: frontmatter 缺少闭合标记 ---")
        m_name = re.search(r"(?m)^name:\s*(\S+)", text)
        if not m_name:
            findings.append(f"{skills_rel}/{sd.name}/SKILL.md: 缺 frontmatter name")
        elif m_name.group(1) != sd.name:
            findings.append(f"{skills_rel}/{sd.name}/SKILL.md: frontmatter name（{m_name.group(1)}）与目录名不一致")
        if not re.search(r"(?m)^description:\s*\S+", text):
            findings.append(f"{skills_rel}/{sd.name}/SKILL.md: 缺 frontmatter description")
        if len(text.encode("utf-8")) > SKILL_SIZE_WARN:
            print(f"[提示] {skills_rel}/{sd.name}/SKILL.md 超过 {SKILL_SIZE_WARN} 字节，建议拆层")
    return findings


def cmd_audit(args, repo):
    print(f"audit: 扫描仓库（REPO={repo}）")
    findings = audit_repo(repo)
    if findings:
        for f in findings:
            print(f"[FAIL] {f}")
        sys.exit(2)
    print("audit: 未发现密钥、硬编码本地路径或 frontmatter 缺失")
