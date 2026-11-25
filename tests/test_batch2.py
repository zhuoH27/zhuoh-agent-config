# -*- coding: utf-8 -*-
"""批次2回归：prompt 链接保护、doctor 措辞、废弃告知、兜底幂等。"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PS = shutil.which("powershell.exe")
TS = "20260101_000000"
DROP_ENV = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODEX_SANDBOX",
            "AGENT_CONFIG_TS"}


def run_engine(*args, home=None, repo=REPO):
    cmd = [sys.executable, "-I", str(repo / "scripts" / "agent_sync.py"), *map(str, args)]
    if home is not None:
        cmd += ["--home", str(home)]
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env["AGENT_CONFIG_TS"] = TS
    r = subprocess.run(cmd, capture_output=True, cwd=str(repo), env=env, timeout=120)
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    return r.returncode, out


def make_home(tmp_path, host=".codex"):
    home = tmp_path / "home dir"
    home.mkdir(exist_ok=True)
    (home / host).mkdir(parents=True, exist_ok=True)
    return home


def test_prompt_file_symlink_preserved(tmp_path):
    """⑤ prompt 目标是符号链接：跳过，链接不被销毁。"""
    home = make_home(tmp_path)
    pd = home / ".codex" / "prompts"
    pd.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE-ORIGINAL\n", encoding="utf-8")
    link = pd / "sync.md"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"无法创建符号链接: {e}")
    rc, out = run_engine("setup", "--target", "codex", home=home)
    assert rc == 0, out
    assert "目标是链接" in out and "人工处理" in out
    assert link.is_symlink(), "链接被销毁了"
    assert outside.read_text(encoding="utf-8") == "OUTSIDE-ORIGINAL\n"


def test_doctor_notes_foreign_tool_link(tmp_path):
    """⑥ 技能目录链接指向仓库外：doctor 提示可能由其它工具管理，且不再报不一致。"""
    home = make_home(tmp_path, ".claude")
    foreign = tmp_path / "magpie-lib" / "zhuoh-code-standards"
    shutil.copytree(REPO / "skills" / "zhuoh-code-standards", foreign)
    hs = home / ".claude" / "skills"
    hs.mkdir(parents=True)
    try:
        os.symlink(foreign, hs / "zhuoh-code-standards", target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"无法创建符号链接: {e}")
    rc, out = run_engine("doctor", "--target", "claude", home=home)
    assert "其它工具管理" in out, out
    assert "请人工确认归属" in out
    assert "与仓库不一致: zhuoh-code-standards" not in out, "不应再报内容不一致"


def test_deprecated_skill_flagged(tmp_path):
    """⑦ 已废弃技能出现在「现有其他 Skill」时带 [已废弃] 标注。"""
    home = make_home(tmp_path, ".claude")
    hs = home / ".claude" / "skills"
    (hs / "zhuoh-config-sync").mkdir(parents=True)
    (hs / "zhuoh-config-sync" / "SKILL.md").write_text(
        "---\nname: zhuoh-config-sync\ndescription: old\n---\n", encoding="utf-8")
    rc, out = run_engine("setup", "--dry-run", "--target", "claude", home=home)
    assert rc == 0
    assert "[已废弃" in out and "sync-back" in out


def test_fallback_idempotent_no_backup_duplication(tmp_path):
    """⑧ 兜底重复运行：内容相同不再备份、不再重复写入。"""
    if PS is None:
        pytest.skip("powershell.exe 不可用")
    home = tmp_path / "home dir"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env["PATH"] = ""
    env["USERPROFILE"] = str(home)
    env["HOME"] = str(home)
    env["AGENT_CONFIG_TS"] = TS
    INSTALL = REPO / "install.ps1"

    def run_fallback(ts):
        env2 = dict(env, AGENT_CONFIG_TS=ts)
        r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", str(INSTALL), "--target", "agents", "--home", str(home),
                            "--mode", "replace"],
                           capture_output=True, env=env2, timeout=180, cwd=str(REPO))
        return r.returncode, (r.stdout or b"").decode("utf-8", "replace")

    rc, out = run_fallback("20260101_000001")
    assert rc == 0, out
    baks1 = list((home / ".zhuoh-agent-backup").rglob("*.bak")) if (home / ".zhuoh-agent-backup").exists() else []
    rc2, out2 = run_fallback("20260101_000002")
    assert rc2 == 0
    assert "已最新" in out2
    baks2 = list((home / ".zhuoh-agent-backup").rglob("*.bak")) if (home / ".zhuoh-agent-backup").exists() else []
    assert baks2 == baks1, "幂等运行不应新增备份"
    assert "备份:" not in out2, "内容相同时不应产生备份动作"
