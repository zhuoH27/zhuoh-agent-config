# -*- coding: utf-8 -*-
"""install.ps1 裸机兜底路径黑盒测试 + 字节契约。

PATH 清空强迫 Get-Command 找不到 Python，必然进入裸机兜底分支；
全部隔离到临时 home（带空格路径），绝不触碰真实 ~/.agents 等。
每例先断言兜底横幅，确保没有误入引擎分支。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.ps1"
TS = "20260101_000000"
BANNER = "未检测到 Python，使用裸机兜底模式"
DROP_ENV = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODEX_SANDBOX",
            "AGENT_CONFIG_TS"}

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="install.ps1 兜底仅 Windows")
PS = shutil.which("powershell.exe")


def run_fallback(*args, home, env_extra=None):
    if PS is None:
        pytest.skip("powershell.exe 不可用")
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env["PATH"] = ""  # 强迫 Get-Command 找不到 python → 兜底分支
    env["USERPROFILE"] = str(home)
    env["HOME"] = str(home)
    env["AGENT_CONFIG_TS"] = TS
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", str(INSTALL), *args],
                       capture_output=True, env=env, timeout=120, cwd=str(REPO))
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    return r.returncode, out


def make_home(tmp_path):
    d = tmp_path / "home dir"  # 带空格：验证 -File 参数透传
    d.mkdir()
    return d


def test_fallback_agents_auto_success(tmp_path):
    """auto 只检测到 ~/.agents：单宿主成功，规则与 skills 落盘。"""
    home = make_home(tmp_path)
    (home / ".agents").mkdir()
    rc, out = run_fallback("--target", "auto", "--home", str(home), home=home)
    assert BANNER in out
    assert rc == 0
    assert "完成（兜底模式）" in out
    rules = home / ".agents" / "AGENTS.md"
    assert "全局核心铁律" in rules.read_text(encoding="utf-8")
    assert (home / ".agents" / "skills" / "zhuoh-code-standards" / "SKILL.md").exists()


def test_fallback_auto_conflict_two_hosts(tmp_path):
    """auto 同时检测到 ~/.claude 与 ~/.codex：报错退出且不落任何文件。"""
    home = make_home(tmp_path)
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    rc, out = run_fallback("--target", "auto", "--home", str(home), home=home)
    assert BANNER in out
    assert rc != 0
    assert "检测到多个宿主" in out
    assert "claude" in out and "codex" in out
    assert not (home / ".claude" / "CLAUDE.md").exists()
    assert not (home / ".codex" / "AGENTS.md").exists()


def test_fallback_default_abort_keeps_rules(tmp_path):
    """默认 --mode abort：已存在规则文件时停止，内容一个字节不动。"""
    home = make_home(tmp_path)
    (home / ".agents").mkdir()
    rules = home / ".agents" / "AGENTS.md"
    sentinel = "SENTINEL-KEEP-ME"
    rules.write_text(sentinel, encoding="utf-8")
    rc, out = run_fallback("--target", "agents", "--home", str(home), home=home)
    assert BANNER in out
    assert rc != 0
    assert "已存在" in out
    assert rules.read_text(encoding="utf-8") == sentinel


def test_fallback_replace_creates_backup(tmp_path):
    """显式 --mode replace：覆盖前备份到 ~/.zhuoh-agent-backup/<TS>/，命名符合铁律第 2 条。"""
    home = make_home(tmp_path)
    (home / ".agents").mkdir()
    rules = home / ".agents" / "AGENTS.md"
    sentinel = "OLD-RULES-CONTENT"
    rules.write_text(sentinel, encoding="utf-8")
    rc, out = run_fallback("--target", "agents", "--home", str(home),
                           "--mode", "replace", home=home)
    assert BANNER in out
    assert rc == 0
    bak = home / ".zhuoh-agent-backup" / TS / f"AGENTS_{TS}.md.bak"
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == sentinel
    assert "全局核心铁律" in rules.read_text(encoding="utf-8")


def test_fallback_symlink_rules_refused(tmp_path):
    """规则文件是符号链接：拒绝写入（防 Copy-Item 穿链接写穿目标）。"""
    home = make_home(tmp_path)
    (home / ".agents").mkdir()
    target = home / "outside.md"
    target.write_text("OUTSIDE-SENTINEL", encoding="utf-8")
    rules = home / ".agents" / "AGENTS.md"
    try:
        os.symlink(target, rules)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"无法创建符号链接: {e}")
    rc, out = run_fallback("--target", "agents", "--home", str(home), home=home)
    assert BANNER in out
    assert rc != 0
    assert "拒绝写入" in out
    assert target.read_text(encoding="utf-8") == "OUTSIDE-SENTINEL"


def test_fallback_dangling_rules_refused(tmp_path):
    """规则文件是悬空链接：Test-Link 的父目录列举分支必须识别并拒绝。"""
    home = make_home(tmp_path)
    (home / ".agents").mkdir()
    rules = home / ".agents" / "AGENTS.md"
    missing = home / "gone.md"  # 不存在 → 悬空
    try:
        os.symlink(missing, rules)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"无法创建符号链接: {e}")
    rc, out = run_fallback("--target", "agents", "--home", str(home), home=home)
    assert BANNER in out
    assert rc != 0
    assert "拒绝写入" in out
    assert not missing.exists()


def test_fallback_nested_dir_link_skipped(tmp_path):
    """技能中间目录是链接：跳过其下文件，目标侧一个字节不写（红队 S1 回归；symlink/junction 同为 ReparsePoint）。"""
    home = make_home(tmp_path)
    (home / ".agents").mkdir()
    rc, out = run_fallback("--target", "agents", "--home", str(home), home=home)
    assert rc == 0
    ref = home / ".agents" / "skills" / "zhuoh-ppt-maker" / "references"
    shutil.rmtree(ref)
    outside = tmp_path / "outside dir"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("KEEP", encoding="utf-8")
    try:
        os.symlink(outside, ref, target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"无法创建符号链接: {e}")
    rc, out = run_fallback("--target", "agents", "--home", str(home),
                           "--mode", "replace", home=home)
    assert BANNER in out
    assert rc == 0
    assert "中间目录" in out and "人工处理" in out
    assert sorted(p.name for p in outside.iterdir()) == ["sentinel.txt"]


def test_fallback_skills_root_link_skipped(tmp_path):
    """skills 根目录是链接：跳过全部技能，规则文件照常写入（红队 S1 回归）。"""
    home = make_home(tmp_path)
    agents = home / ".agents"
    agents.mkdir()
    outside = tmp_path / "outside skills"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("KEEP", encoding="utf-8")
    try:
        os.symlink(outside, agents / "skills", target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"无法创建符号链接: {e}")
    rc, out = run_fallback("--target", "agents", "--home", str(home), home=home)
    assert BANNER in out
    assert rc == 0
    assert "跳过 skills" in out and "人工处理" in out
    assert "全局核心铁律" in (agents / "AGENTS.md").read_text(encoding="utf-8")
    assert sorted(p.name for p in outside.iterdir()) == ["sentinel.txt"]


def test_fallback_skill_file_link_skipped(tmp_path):
    """技能文件是链接：跳过该文件，链接与目标内容均不动（红队 S1/G5 回归）。"""
    home = make_home(tmp_path)
    (home / ".agents").mkdir()
    rc, out = run_fallback("--target", "agents", "--home", str(home), home=home)
    assert rc == 0
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE-SENTINEL", encoding="utf-8")
    tgt = home / ".agents" / "skills" / "zhuoh-code-standards" / "SKILL.md"
    tgt.unlink()
    try:
        os.symlink(outside, tgt)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"无法创建符号链接: {e}")
    rc, out = run_fallback("--target", "agents", "--home", str(home),
                           "--mode", "replace", home=home)
    assert BANNER in out
    assert rc == 0
    assert "人工处理" in out
    assert outside.read_text(encoding="utf-8") == "OUTSIDE-SENTINEL"
    assert tgt.is_symlink()  # 链接未被替换


def test_install_ps1_byte_contract():
    """UTF-8 BOM + 全 CRLF：PS 5.1 无 BOM 会把中文按 GBK 解，换行契约由 .gitattributes 约定。"""
    data = INSTALL.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf"), "install.ps1 应为 UTF-8 BOM"
    body = data[3:]
    assert body.count(b"\n") == body.count(b"\r\n"), "install.ps1 应全为 CRLF"
    assert body.count(b"\r") == body.count(b"\r\n"), "不应有孤立 CR"
