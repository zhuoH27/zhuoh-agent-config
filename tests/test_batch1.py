# -*- coding: utf-8 -*-
"""批次1回归：preflight 零写入、link 三分法、BOM 收敛、audit 白名单。"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BEGIN = "<!-- BEGIN: global-iron-rules -->"
END = "<!-- END: global-iron-rules -->"


def run_engine(*args, home=None, repo=REPO):
    cmd = [sys.executable, "-I", str(repo / "scripts" / "agent_sync.py"), *map(str, args)]
    if home is not None:
        cmd += ["--home", str(home)]
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID")}
    env["AGENT_CONFIG_TS"] = "20260101_000000"
    r = subprocess.run(cmd, capture_output=True, cwd=str(repo), env=env, timeout=120)
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    return r.returncode, out


def make_home(tmp_path, *hosts):
    home = tmp_path / "home dir"
    home.mkdir(exist_ok=True)
    for h in hosts:
        (home / h).mkdir(parents=True, exist_ok=True)
    return home


# ---------- ① preflight ----------

def test_preflight_blocks_partial_write(tmp_path):
    """--target both：codex 标记异常时，claude 也不写入（对比旧行为的半截状态）。"""
    home = make_home(tmp_path, ".claude", ".codex")
    bad = home / ".codex" / "AGENTS.md"
    bad.write_text("USER CONTENT\n" + BEGIN + "\nbody\n", encoding="utf-8")
    rc, out = run_engine("setup", "--target", "both", home=home)
    assert rc == 1, out
    assert "阻塞" in out and "标记异常" in out
    assert not (home / ".claude" / "CLAUDE.md").exists(), "preflight 失败却写入了 claude"
    assert "USER CONTENT" in bad.read_text(encoding="utf-8")


def test_preflight_skill_target_is_file(tmp_path):
    """技能目标被普通文件占用：apply 也应可读报错（不再裸 traceback）。"""
    home = make_home(tmp_path, ".claude")
    (home / ".claude" / "skills").mkdir()
    (home / ".claude" / "skills" / "zhuoh-code-standards").write_text("i am a file", encoding="utf-8")
    rc, out = run_engine("setup", "--target", "claude", home=home)
    assert rc == 1, out
    assert "不是目录" in out
    assert "Traceback" not in out


def test_preflight_dry_run_reports_same_blocks(tmp_path):
    """dry-run 与 apply 走同一 preflight：dry-run 也必须报出阻塞。"""
    home = make_home(tmp_path, ".claude")
    (home / ".claude" / "skills").mkdir()
    (home / ".claude" / "skills" / "zhuoh-code-standards").write_text("x", encoding="utf-8")
    rc, out = run_engine("setup", "--dry-run", "--target", "claude", home=home)
    assert rc == 1
    assert "不是目录" in out


# ---------- ③ link 三分法 ----------

def test_link_mode_redirects_stale_link(tmp_path):
    """旧克隆仍在、链接指向旧内容：重定向到当前源，doctor 全绿。"""
    import subprocess as sp
    old = tmp_path / "oldclone"
    shutil.copytree(REPO, old, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    sk = old / "skills" / "zhuoh-code-standards" / "SKILL.md"
    sk.write_text(sk.read_text(encoding="utf-8") + "\n<!-- OLD -->\n", encoding="utf-8")
    home = make_home(tmp_path, ".claude")
    run_engine("setup", "--target", "claude", "--skill-mode", "link", home=home, repo=old)
    host = home / ".claude" / "skills" / "zhuoh-code-standards"
    assert host.is_symlink() and "<!-- OLD -->" in (host / "SKILL.md").read_text(encoding="utf-8")
    # 现在用当前仓库（新克隆）更新
    rc, out = run_engine("setup", "--target", "claude", "--skill-mode", "link", home=home)
    assert rc == 0, out
    assert "重定向" in out
    d_rc, d_out = run_engine("doctor", "--target", "claude", home=home)
    assert d_rc == 0, d_out
    assert host.resolve().is_relative_to(REPO.resolve())
    # 旧克隆的内容没有被破坏
    assert "<!-- OLD -->" in sk.read_text(encoding="utf-8")


def test_link_mode_heals_dangling_link(tmp_path):
    """旧克隆删除后链接悬空：删除悬空链接并重建，doctor 全绿。"""
    old = tmp_path / "oldclone"
    shutil.copytree(REPO, old, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    home = make_home(tmp_path, ".claude")
    run_engine("setup", "--target", "claude", "--skill-mode", "link", home=home, repo=old)
    shutil.rmtree(old)
    host = home / ".claude" / "skills" / "zhuoh-code-standards"
    assert host.is_symlink() and not host.exists()  # 悬空
    rc, out = run_engine("setup", "--target", "claude", "--skill-mode", "link", home=home)
    assert rc == 0, out
    assert "悬空" in out
    d_rc, d_out = run_engine("doctor", "--target", "claude", home=home)
    assert d_rc == 0, d_out


def test_link_mode_foreign_tool_copy_untouched(tmp_path):
    """链接指向仓库外且内容一致（其它工具管理的副本）：跳过不重定向。"""
    home = make_home(tmp_path, ".claude")
    foreign = tmp_path / "magpie-lib" / "zhuoh-code-standards"
    shutil.copytree(REPO / "skills" / "zhuoh-code-standards", foreign)
    hs = home / ".claude" / "skills"
    hs.mkdir()
    os.symlink(foreign, hs / "zhuoh-code-standards", target_is_directory=True)
    rc, out = run_engine("setup", "--target", "claude", "--skill-mode", "link", home=home)
    assert rc == 0, out
    assert "跳过" in out and "内容与源一致" in out
    assert (hs / "zhuoh-code-standards").resolve().is_relative_to(foreign.parent)


# ---------- ④ BOM 收敛 ----------

def test_bom_only_drift_strips_and_converges(tmp_path):
    """已安装 SKILL.md 仅带 BOM：setup 备份后剥离，doctor 不再报不一致。"""
    home = make_home(tmp_path, ".claude")
    run_engine("setup", "--target", "claude", home=home)
    sk = home / ".claude" / "skills" / "zhuoh-code-standards" / "SKILL.md"
    d = sk.read_bytes()
    sk.write_bytes(b"\xef\xbb\xbf" + d)
    rc, out = run_engine("setup", "--target", "claude", home=home)
    assert rc == 0
    assert "仅剥离 BOM" in out
    assert sk.read_bytes()[:3] != b"\xef\xbb\xbf"
    d_rc, d_out = run_engine("doctor", "--target", "claude", home=home)
    assert d_rc == 0, d_out


# ---------- ② audit 白名单 ----------

def test_audit_catches_finegrained_pat_and_unc_and_drv(tmp_path):
    """三条新模式均命中；白名单只豁免精确字符串。"""
    victim = tmp_path / "repo"
    shutil.copytree(REPO, victim, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    doc = victim / "AGENTS.md"
    lines = [
        "\npat: github_pat_" + "A" * 70,
        "unc: \\\\\\\\nas01\\\\share\\\\x.xlsx",
        "drv: D:\\work\\p.csv",
    ]
    doc.write_text(doc.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")
    rc, out = run_engine("audit", "--repo", victim)
    assert rc == 2
    assert "fine-grained PAT" in out
    assert "硬编码本地路径" in out
    # 白名单精确豁免 unc 命中后其余仍报
    import json
    (victim / "audit-allowlist.json").write_text(
        json.dumps({"exact_strings": ["\\\\\\\\nas01\\\\share\\\\x.xlsx"]}), encoding="utf-8")
    rc2, out2 = run_engine("audit", "--repo", victim)
    assert rc2 == 2
    assert "nas01" not in out2, "白名单应豁免该精确串"
    assert "fine-grained PAT" in out2, "其余命中不被豁免"
    # 被豁免行夹带真密钥仍拦截
    doc.write_text(doc.read_text(encoding="utf-8").replace(
        "drv: D:\\work\\p.csv", "drv: D:\\work\\p.csv ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"), encoding="utf-8")
    rc3, out3 = run_engine("audit", "--repo", victim)
    assert rc3 == 2 and "GitHub Token" in out3


def test_audit_repo_itself_still_clean():
    """本仓库对新模式零误报（含 audit.py 自身源码）。"""
    rc, out = run_engine("audit", "--repo", REPO)
    assert rc == 0, out
