# -*- coding: utf-8 -*-
"""agent_sync 引擎黑盒测试。

全部通过 monkeypatch/环境变量隔离真实 HOME（绝不触碰真实 ~/.codex 或 ~/.claude）。
契约继承自 test_install.py v2.2.0 的语义断言（标记异常、备份命名、幂等提示等）。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "scripts" / "agent_sync.py"
TS = "20260101_000000"
BEGIN = "<!-- BEGIN: global-iron-rules -->"
END = "<!-- END: global-iron-rules -->"
DROP_ENV = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODEX_SANDBOX",
            "AGENT_CONFIG_TS"}


def run_engine(*args, home=None, env_extra=None, repo=REPO):
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    env["AGENT_CONFIG_TS"] = TS
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([sys.executable, "-I", str(ENGINE), *args, "--repo", str(repo)],
                       capture_output=True, env=env, timeout=120, cwd=str(REPO))
    # Windows 控制台编码坑：子进程输出统一按 UTF-8 解（引擎端已 reconfigure）
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    return r.returncode, out


def expected_rules():
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    b = text.index(BEGIN)
    e = text.index(END) + len(END)
    return text[b:e].strip("\n") + "\n"


def skill_text(name):
    return (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def rules_path(home, key="claude"):
    name = "CLAUDE.md" if key == "claude" else "AGENTS.md"
    return home / ("." + key) / name


def make_home(tmp_path):
    d = tmp_path / "home dir"  # 带空格：验证参数透传
    d.mkdir()
    return d


def read(p):
    return Path(p).read_bytes()


def write(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    Path(p).write_bytes(data)


def norm(data):
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return data.replace("\r\n", "\n").replace("\r", "\n")


def block_variant(extra_line):
    return expected_rules().replace(END, extra_line + "\n" + END, 1)


# --- setup 基线 ---

def test_version():
    rc, out = run_engine("--version")
    assert rc == 0
    assert "agent-config 3.2.0" in out


def test_fresh_apply_claude(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "新建" in out
    p = rules_path(home)
    assert p.exists()
    assert read(p)[:3] != b"\xef\xbb\xbf"
    assert norm(read(p)) == expected_rules()
    for name in ("zhuoh-code-standards", "zhuoh-ppt-maker", "zhuoh-paper-writing",
                 "zhuoh-idea-evaluation", "zhuoh-paper-review"):
        sp = home / ".claude" / "skills" / name / "SKILL.md"
        assert sp.exists()
        assert norm(read(sp)) == skill_text(name)


def test_dry_run_writes_nothing(tmp_path):
    home = make_home(tmp_path)
    (home / ".codex").mkdir()
    rc, out = run_engine("setup", "--dry-run", "--target", "codex", "--home", str(home))
    assert rc == 0, out
    assert "dry-run" in out
    assert "未写入任何配置文件" in out
    assert not (home / ".codex" / "AGENTS.md").exists()
    assert not (home / ".codex" / "skills").exists()


def test_idempotent_second_apply(tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_engine("setup", "--target", "codex", "--home", str(home))
    assert rc == 0
    rc, out = run_engine("setup", "--target", "codex", "--home", str(home))
    assert rc == 0, out
    assert "跳过" in out
    assert "已最新" in out


def test_apply_alias_accepted(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("setup", "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert rules_path(home).exists()


def test_target_agents(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("setup", "--target", "agents", "--home", str(home))
    assert rc == 0, out
    p = home / ".agents" / "AGENTS.md"
    assert p.exists()
    assert norm(read(p)) == expected_rules()
    assert (home / ".agents" / "skills" / "zhuoh-code-standards" / "SKILL.md").exists()


def test_target_both(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("setup", "--target", "both", "--home", str(home))
    assert rc == 0, out
    assert rules_path(home, "claude").exists()
    assert rules_path(home, "codex").exists()


def test_prompts_copied_for_codex(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("setup", "--target", "codex", "--home", str(home))
    assert rc == 0, out
    assert "Prompt sync.md: 新建" in out
    p = home / ".codex" / "prompts" / "sync.md"
    assert p.exists()
    assert norm(read(p)) == norm((REPO / "prompts" / "sync.md").read_bytes())


def test_prompts_overwrite_backup(tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_engine("setup", "--target", "codex", "--home", str(home))
    assert rc == 0
    p = home / ".codex" / "prompts" / "sync.md"
    write(p, "旧版提示词\n")
    rc, out = run_engine("setup", "--target", "codex", "--home", str(home))
    assert rc == 0, out
    bak = home / ".zhuoh-agent-backup" / TS / f"sync_{TS}.md.bak"
    assert bak.exists()
    assert norm(read(bak)) == "旧版提示词\n"


# --- auto 探测 ---

def test_auto_env_claude(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("setup", "--target", "auto", "--home", str(home),
                         env_extra={"CLAUDECODE": "1"})
    assert rc == 0, out
    assert "环境变量 -> claude" in out
    assert rules_path(home, "claude").exists()
    assert not rules_path(home, "codex").exists()


def test_auto_env_codex_thread(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("setup", "--target", "auto", "--home", str(home),
                         env_extra={"CODEX_THREAD_ID": "t-1"})
    assert rc == 0, out
    assert "环境变量 -> codex" in out


def test_auto_single_host_dir(tmp_path):
    home = make_home(tmp_path)
    (home / ".codex").mkdir()
    rc, out = run_engine("setup", "--dry-run", "--target", "auto", "--home", str(home))
    assert rc == 0, out
    assert "仅存在 ~/.codex" in out


def test_auto_two_hosts_conflict(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    rc, out = run_engine("setup", "--target", "auto", "--home", str(home))
    assert rc != 0
    assert "同时检测到 ~/.claude 与 ~/.codex" in out


def test_auto_multi_hosts_message(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()
    (home / ".agents").mkdir()
    rc, out = run_engine("setup", "--target", "auto", "--home", str(home))
    assert rc != 0
    assert "检测到多个宿主" in out


def test_auto_no_hosts_error(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("setup", "--target", "auto", "--home", str(home))
    assert rc != 0
    assert "未检测到 ~/.claude 或 ~/.codex" in out


# --- 规则文件合并语义 ---

def test_append_preserves_content(tmp_path):
    home = make_home(tmp_path)
    old = "我的已有配置\n\n段落A\n\n\n"
    write(rules_path(home), old)
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    got = norm(read(rules_path(home)))
    assert got == old + "\n" + expected_rules()


def test_replace_block_keeps_outside(tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "# 我的项目\n" + block_variant("旧版内容") + "\n尾部说明\n")
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    got = norm(read(rules_path(home)))
    assert got.startswith("# 我的项目\n")
    assert got.endswith("\n尾部说明\n")
    assert expected_rules() in got


def test_crlf_target_preserved(tmp_path):
    home = make_home(tmp_path)
    raw = "# 头部\r\n\r\n" + block_variant("旧版内容").replace("\n", "\r\n") + "\r\n尾部\r\n"
    write(rules_path(home), raw)
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    got = read(rules_path(home))
    assert b"\r\n" in got
    assert expected_rules() in norm(got)


def test_legacy_hint_blocks_by_default(tmp_path):
    home = make_home(tmp_path)
    old = "# 全局核心铁律（旧版手写）\n\n不可逆操作确认流程……\n"
    write(rules_path(home), old)
    rc, out = run_engine("setup", "--dry-run", "--target", "claude", "--home", str(home))
    assert rc == 0  # dry-run 只警告不停止
    assert "[警告] 疑似已有旧版未受管铁律" in out
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "[警告]" in out  # apply 也仅警告（追加语义与原 v2.2.0 一致）
    assert norm(read(rules_path(home))).startswith(old.rstrip("\n"))


def test_marker_anomaly_stops(tmp_path):
    home = make_home(tmp_path)
    old = expected_rules() + expected_rules()
    write(rules_path(home), old)
    rc, out = run_engine("setup", "--dry-run", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "标记异常" in out


def test_marker_inline_rejected(tmp_path):
    home = make_home(tmp_path)
    old = "前缀 " + BEGIN + "\n旧内容\n" + END + " 后缀\n"
    write(rules_path(home), old)
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "标记异常" in out
    assert norm(read(rules_path(home))) == old


def test_mode_replace_full_file(tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "自定义指令\n\n更多内容\n")
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home),
                         "--mode", "replace", "--skill-mode", "copy")
    assert rc == 0, out
    assert "整文件替换" in out
    assert norm(read(rules_path(home))) == expected_rules()


def test_utf8_reject(tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), b"\xd6\xd0\xce\xc4 gb\n")
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "无法按 UTF-8 解码" in out


# --- 备份契约 ---

def test_backup_naming_and_location(tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "自定义指令\n")
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home),
                         "--mode", "replace")
    assert rc == 0, out
    bak = home / ".zhuoh-agent-backup" / TS / f"CLAUDE_{TS}.md.bak"
    assert bak.exists()
    assert norm(read(bak)) == "自定义指令\n"


def test_backup_collision_suffix(tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), block_variant("版本1"))
    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0
    write(rules_path(home), block_variant("版本2"))
    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0
    b1 = home / ".zhuoh-agent-backup" / TS / f"CLAUDE_{TS}.md.bak"
    b2 = home / ".zhuoh-agent-backup" / TS / f"CLAUDE_{TS}_2.md.bak"
    assert b1.exists() and b2.exists()
    assert "版本1" in norm(read(b1))
    assert "版本2" in norm(read(b2))


def test_append_backs_up(tmp_path):
    """README 契约：无受管标记的 append 写入前也先备份（不限于带警告的场景）。"""
    home = make_home(tmp_path)
    write(rules_path(home), "自定义指令\n")
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    bak = home / ".zhuoh-agent-backup" / TS / f"CLAUDE_{TS}.md.bak"
    assert bak.exists()
    assert norm(read(bak)) == "自定义指令\n"


def test_bom_strip_backs_up(tmp_path):
    """仅剥离 BOM 的写入路径同样先备份。"""
    home = make_home(tmp_path)
    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0
    p = rules_path(home)
    write(p, b"\xef\xbb\xbf" + read(p))
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "仅剥离 BOM" in out
    bak = home / ".zhuoh-agent-backup" / TS / f"CLAUDE_{TS}.md.bak"
    assert bak.exists()
    assert read(p)[:3] != b"\xef\xbb\xbf"


def test_skill_replace_backup_outside_skill_dir(tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0
    sp = home / ".claude" / "skills" / "zhuoh-code-standards" / "SKILL.md"
    modified = skill_text("zhuoh-code-standards") + "\n额外一行\n"
    write(sp, modified)
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert norm(read(sp)) == skill_text("zhuoh-code-standards")
    assert not list((home / ".claude" / "skills").rglob("*.bak")), "技能目录内不得残留 .bak"
    bak = home / ".zhuoh-agent-backup" / TS / f"SKILL_{TS}.md.bak"
    assert bak.exists()
    assert norm(read(bak)) == modified


# --- 技能目录行为 ---

def test_extra_skill_files_untouched(tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0
    extra = home / ".claude" / "skills" / "zhuoh-code-standards" / "extra.txt"
    write(extra, "x\n")
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert extra.exists()


def test_skill_references_updated_and_doctored(tmp_path):
    repo = make_repo_copy(tmp_path)
    home = make_home(tmp_path)
    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home), repo=repo)
    assert rc == 0
    ref_src = repo / "skills" / "zhuoh-ppt-maker" / "references" / "layout-guide.md"
    ref_tgt = home / ".claude" / "skills" / "zhuoh-ppt-maker" / "references" / "layout-guide.md"
    assert ref_tgt.exists()
    # 模拟仓库升级 references
    write(ref_src, norm(read(ref_src)) + "\n新增参考行\n")
    rc, out = run_engine("doctor", "--target", "claude", "--home", str(home), repo=repo)
    assert rc == 2 and "layout-guide.md" in out
    rc, out = run_engine("setup", "--target", "claude", "--home", str(home), repo=repo)
    assert rc == 0, out
    assert "新增参考行" in norm(read(ref_tgt))
    assert (home / ".zhuoh-agent-backup" / TS / f"layout-guide_{TS}.md.bak").exists()
    rc, out = run_engine("doctor", "--target", "claude", "--home", str(home), repo=repo)
    assert rc == 0, out


def test_overlap_hint(tmp_path):
    home = make_home(tmp_path)
    write(home / ".claude" / "skills" / "code-standards" / "SKILL.md", "旧版技能\n")
    (home / ".claude" / "skills" / "my-tool").mkdir(parents=True)
    rc, out = run_engine("setup", "--dry-run", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "code-standards ≈ zhuoh-code-standards" in out
    assert "my-tool" in out


# --- doctor / audit / status ---

def test_doctor_healthy(tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0
    rc, out = run_engine("doctor", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "全部健康" in out


def test_doctor_detects_tamper(tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_engine("setup", "--target", "claude", "--home", str(home))
    assert rc == 0
    p = rules_path(home)
    write(p, norm(read(p)).replace("# 全局核心铁律", "# 被篡改的标题"))
    rc, out = run_engine("doctor", "--target", "claude", "--home", str(home))
    assert rc == 2
    assert "规则文件" in out and "不一致" in out


def make_repo_copy(tmp_path):
    """写回类测试的沙盒仓库副本：绝不污染真实仓库。"""
    victim = tmp_path / "repo"
    shutil.copytree(REPO, victim, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".pytest_cache"))
    return victim


def test_audit_catches_fake_key(tmp_path):
    victim = make_repo_copy(tmp_path)
    write(victim / "leaked.md", "token: 'abcdefgh12345678'\n")
    rc, out = run_engine("audit", repo=victim)
    assert rc == 2, out
    assert "leaked.md" in out


def test_audit_excludes_glob_dirs(tmp_path):
    """AUDIT_EXCLUDE_DIRS 的 _t* 是通配排除，不是字面量。"""
    victim = make_repo_copy(tmp_path)
    write(victim / "_t9" / "leaked.md", "token: 'abcdefgh12345678'\n")
    rc, out = run_engine("audit", repo=victim)
    assert rc == 0, out


def test_audit_scans_underscore_t_files(tmp_path):
    """_t* 通配只排除目录分量：同名文件（含大小写变体）必须仍被扫描。"""
    victim = make_repo_copy(tmp_path)
    write(victim / "_Token.md", "token: 'abcdefgh12345678'\n")
    write(victim / "src" / "_tconf.py", "token: 'abcdefgh12345678'\n")
    rc, out = run_engine("audit", repo=victim)
    assert rc == 2, out
    assert "_Token.md" in out


def test_audit_clean_on_baseline():
    rc, out = run_engine("audit")
    assert rc == 0, out
    assert "未发现" in out


def test_status_json(tmp_path):
    home = make_home(tmp_path)
    rc, out = run_engine("status", "--json", "--home", str(home))
    assert rc == 0, out
    data = json.loads(out)
    assert data["version"] == "3.2.0"
    assert set(data["hosts"]) == {"claude", "codex", "agents"}
