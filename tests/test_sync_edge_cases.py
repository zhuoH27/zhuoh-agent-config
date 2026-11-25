# -*- coding: utf-8 -*-
"""agent_sync 引擎安全与边界回归测试。

专门覆盖审查修复的边界问题，独立成文件以保持各测试文件 ≤ 600 行。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "scripts" / "agent_sync.py"
TS = "20260101_000000"
BEGIN = "<!-- BEGIN: global-iron-rules -->"
END = "<!-- END: global-iron-rules -->"
DROP_ENV = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODEX_SANDBOX",
            "AGENT_CONFIG_TS"}


def run_engine(*args, home=None, repo=REPO):
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    env["AGENT_CONFIG_TS"] = TS
    r = subprocess.run([sys.executable, "-I", str(ENGINE), *args, "--repo", str(repo)],
                       capture_output=True, env=env, timeout=120, cwd=str(REPO))
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    return r.returncode, out


def test_dry_run_link_mode_writes_nothing(tmp_path):
    """--dry-run --skill-mode link 不得创建目录或符号链接。"""
    home = tmp_path / "home dir"
    home.mkdir()
    rc, out = run_engine("setup", "--dry-run", "--skill-mode", "link",
                         "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "将链接" in out
    assert not (home / ".claude" / "skills").exists()
    assert not (home / ".claude" / "CLAUDE.md").exists()


def test_reversed_markers_rejected(tmp_path):
    """END 在 BEGIN 之前必须判标记异常并拒绝改写。"""
    home = tmp_path / "home dir"
    rules = home / ".claude" / "CLAUDE.md"
    rules.parent.mkdir(parents=True)
    broken = f"{END}\n中间内容\n{BEGIN}\n"
    rules.write_text(broken, encoding="utf-8")
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "标记异常" in out
    assert rules.read_text(encoding="utf-8") == broken


def test_status_reports_installed_skills_only(tmp_path):
    """空白 home 报 0 个技能，安装 claude 后仅 claude 报满 6 个技能。"""
    home = tmp_path / "home dir"
    home.mkdir()
    rc, out = run_engine("status", "--json", "--home", str(home))
    assert rc == 0
    data = json.loads(out)
    assert data["hosts"]["claude"]["skills"] == []
    assert data["hosts"]["codex"]["skills"] == []

    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0
    rc, out = run_engine("status", "--json", "--home", str(home))
    assert rc == 0
    data = json.loads(out)
    assert len(data["hosts"]["claude"]["skills"]) == data["skills_expected"]
    assert data["hosts"]["codex"]["skills"] == []


def test_doctor_checks_codex_prompts(tmp_path):
    """doctor 应检出 ~/.codex/prompts/sync.md 缺失或被篡改。"""
    home = tmp_path / "home dir"
    home.mkdir()
    rc, _ = run_engine("setup", "--target", "codex", "--home", str(home))
    assert rc == 0
    rc, out = run_engine("doctor", "--target", "codex", "--home", str(home))
    assert rc == 0, out

    prompt_file = home / ".codex" / "prompts" / "sync.md"
    prompt_file.write_text("被篡改的提示词\n", encoding="utf-8")
    rc, out = run_engine("doctor", "--target", "codex", "--home", str(home))
    assert rc == 2
    assert "Prompt" in out and "sync.md" in out

    prompt_file.unlink()
    rc, out = run_engine("doctor", "--target", "codex", "--home", str(home))
    assert rc == 2
    assert "Prompt 缺失" in out


def test_both_hosts_hierarchical_backups_isolated(tmp_path):
    """--target both 同时更新两个宿主同名 SKILL.md，备份按宿主/技能路径隔离。"""
    home = tmp_path / "home dir"
    home.mkdir()
    rc, _ = run_engine("setup", "--target", "both", "--home", str(home))
    assert rc == 0
    c_skill = home / ".claude" / "skills" / "zhuoh-code-standards" / "SKILL.md"
    x_skill = home / ".codex" / "skills" / "zhuoh-code-standards" / "SKILL.md"
    c_skill.write_text("CLAUDE-CUSTOM\n", encoding="utf-8")
    x_skill.write_text("CODEX-CUSTOM\n", encoding="utf-8")

    rc, out = run_engine("setup", "--target", "both", "--home", str(home))
    assert rc == 0, out
    c_bak = home / ".zhuoh-agent-backup" / TS / "claude" / "skills" / "zhuoh-code-standards" / f"SKILL_{TS}.md.bak"
    x_bak = home / ".zhuoh-agent-backup" / TS / "codex" / "skills" / "zhuoh-code-standards" / f"SKILL_{TS}.md.bak"
    assert c_bak.exists() and x_bak.exists()
    assert c_bak.read_text(encoding="utf-8") == "CLAUDE-CUSTOM\n"
    assert x_bak.read_text(encoding="utf-8") == "CODEX-CUSTOM\n"


def test_prompts_dir_symlink_skipped(tmp_path):
    """~/.codex/prompts 为符号链接时跳过写入，不穿透外部目录。"""
    home = tmp_path / "home dir"
    (home / ".codex").mkdir(parents=True)
    outside = tmp_path / "outside_prompts"
    outside.mkdir()
    (outside / "keep.txt").write_text("KEEP", encoding="utf-8")
    os.symlink(outside, home / ".codex" / "prompts", target_is_directory=True)
    rc, out = run_engine("setup", "--target", "codex", "--home", str(home))
    assert rc == 0, out
    assert "符号链接，跳过" in out
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]


def test_dry_run_backup_collision_preview(tmp_path):
    """已有同秒备份时，dry-run 预览的备份路径应正确递增为 _2。"""
    home = tmp_path / "home dir"
    rules = home / ".claude" / "CLAUDE.md"
    rules.parent.mkdir(parents=True)
    rules.write_text("旧配置\n", encoding="utf-8")
    existing_bak = home / ".zhuoh-agent-backup" / TS / "claude" / f"CLAUDE_{TS}.md.bak"
    existing_bak.parent.mkdir(parents=True)
    existing_bak.write_text("第一次备份\n", encoding="utf-8")
    rc, out = run_engine("setup", "--dry-run", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert f"CLAUDE_{TS}_2.md.bak" in out
