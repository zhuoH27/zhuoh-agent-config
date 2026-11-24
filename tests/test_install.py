# -*- coding: utf-8 -*-
"""agent-config 安装器黑盒测试。

双驱动 install.sh（POSIX sh）与 install.ps1（Windows PowerShell 5.1）。
测试与 CI 需要 Python（pytest）；用户安装机器零依赖。
Windows 上 sh 取 Git 自带的 sh.exe；Linux 上直接用系统 sh。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TS = "20260101_000000"
BEGIN = "<!-- BEGIN: global-iron-rules -->"
END = "<!-- END: global-iron-rules -->"
DROP_ENV = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODEX_SANDBOX"}


def _find_sh():
    exe = shutil.which("sh")
    if exe:
        return exe
    for p in (
        r"C:\Program Files\Git\bin\sh.exe",
        r"C:\Program Files\Git\usr\bin\sh.exe",
        r"C:\Program Files (x86)\Git\bin\sh.exe",
    ):
        if Path(p).exists():
            return p
    return None


SH = _find_sh()
PS1 = shutil.which("powershell.exe") if sys.platform == "win32" else None
PWSH = shutil.which("pwsh")
INSTALLERS = [i for i, avail in (("sh", SH), ("ps1", PS1), ("pwsh", PWSH)) if avail]

pytestmark = pytest.mark.parametrize("installer", INSTALLERS, ids=lambda x: str(x))


def run_installer(installer, *args, home=None, env_extra=None, ts=TS):
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV and k != "AGENT_CONFIG_TS"}
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    if ts is not None:
        env["AGENT_CONFIG_TS"] = ts
    if env_extra:
        env.update(env_extra)
    if installer == "sh":
        cmd = [SH, str(REPO / "install.sh"), *args]
    elif installer == "pwsh":
        cmd = [PWSH, "-NoProfile", "-File", str(REPO / "install.ps1"), *args]
    else:
        cmd = [PS1, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REPO / "install.ps1"), *args]
    r = subprocess.run(cmd, capture_output=True, env=env, timeout=180)
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


def block_variant(extra_line):
    core = expected_rules()
    return core.replace(END, extra_line + "\n" + END, 1)


def make_home(tmp_path):
    d = tmp_path / "home dir"  # 目录名带空格：验证参数透传
    d.mkdir()
    return d


def read(path):
    return Path(path).read_bytes()


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    Path(path).write_bytes(data)


def norm(data):
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return data.replace("\r\n", "\n").replace("\r", "\n")


def test_sh_syntax(installer):
    if SH is None or installer != "sh":
        pytest.skip("非 sh 驱动或无 sh")
    r = subprocess.run([SH, "-n", str(REPO / "install.sh")], capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


def test_version(installer):
    rc, out = run_installer(installer, "--version")
    assert rc == 0
    assert "agent-config 2.2.0" in out


def test_fresh_apply_and_verify(installer, tmp_path):
    home = make_home(tmp_path)
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "新建" in out
    assert "写入" in out
    assert "--verify --target claude" in out  # 回归：下一步提示的 --target 不得被工作变量覆盖
    p = rules_path(home)
    assert p.exists()
    assert read(p)[:3] != b"\xef\xbb\xbf"  # 无 BOM
    assert norm(read(p)) == expected_rules()
    for name in ("zhuoh-code-standards", "zhuoh-ppt-maker", "zhuoh-paper-writing", "zhuoh-idea-evaluation", "zhuoh-paper-review"):
        sp = home / ".claude" / "skills" / name / "SKILL.md"
        assert sp.exists()
        assert norm(read(sp)) == skill_text(name)
    rc, out = run_installer(installer, "--verify", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "全部通过" in out
    assert "FAIL" not in out


def test_dry_run_writes_nothing(installer, tmp_path):
    home = make_home(tmp_path)
    (home / ".codex").mkdir()
    rc, out = run_installer(installer, "--dry-run", "--target", "codex", "--home", str(home))
    assert rc == 0, out
    assert "dry-run" in out
    assert "未写入任何配置文件" in out
    assert not (home / ".codex" / "AGENTS.md").exists()
    assert not (home / ".codex" / "skills").exists()


def test_idempotent_second_apply(installer, tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_installer(installer, "--apply", "--target", "codex", "--home", str(home))
    assert rc == 0
    rc, out = run_installer(installer, "--apply", "--target", "codex", "--home", str(home))
    assert rc == 0, out
    assert "跳过" in out
    assert "已最新" in out
    assert not (home / ".codex" / "_backup").exists()


def test_append_preserves_content_and_blank_lines(installer, tmp_path):
    """回归：追加必须保留原内容（含末尾空行），不吞行。"""
    home = make_home(tmp_path)
    old = "我的已有配置\n\n段落A\n\n\n"
    write(rules_path(home), old)
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "追加受管区块" in out
    got = norm(read(rules_path(home)))
    assert got.startswith("我的已有配置\n\n段落A\n\n\n")
    assert got == old + "\n" + expected_rules()
    rc, out = run_installer(installer, "--verify", "--target", "claude", "--home", str(home))
    assert rc == 0, out


def test_append_missing_trailing_newline(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "我的已有配置")
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    got = norm(read(rules_path(home)))
    assert got == "我的已有配置\n" + "\n" + expected_rules()


def test_replace_block_keeps_outside(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "# 我的项目\n" + block_variant("旧版内容") + "\n尾部说明\n")
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "替换受管区块" in out
    assert "区块差异" in out
    got = norm(read(rules_path(home)))
    assert got.startswith("# 我的项目\n")
    assert got.endswith("\n尾部说明\n")
    assert expected_rules() in got


def test_crlf_target_preserved(installer, tmp_path):
    home = make_home(tmp_path)
    raw = "# 头部\r\n\r\n" + block_variant("旧版内容").replace("\n", "\r\n") + "\r\n尾部\r\n"
    write(rules_path(home), raw)
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    got_bytes = read(rules_path(home))
    assert b"\r\n" in got_bytes
    got = norm(got_bytes)
    assert got.startswith("# 头部\n\n")
    assert got.endswith("\n尾部\n")
    assert expected_rules() in got


def test_mode_replace(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "自定义指令\n\n更多内容\n")
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home),
                            "--mode", "replace")
    assert rc == 0, out
    assert "整文件替换" in out
    assert norm(read(rules_path(home))) == expected_rules()
    bak = home / ".claude" / "_backup" / ("CLAUDE_" + TS + ".md.bak")
    assert bak.exists()
    assert norm(read(bak)) == "自定义指令\n\n更多内容\n"


def test_mode_abort(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "自定义指令\n")
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home),
                            "--mode", "abort")
    assert rc != 0
    assert "abort 停止" in out
    assert norm(read(rules_path(home))) == "自定义指令\n"


def test_target_agents(installer, tmp_path):
    home = make_home(tmp_path)
    rc, out = run_installer(installer, "--apply", "--target", "agents", "--home", str(home))
    assert rc == 0, out
    p = home / ".agents" / "AGENTS.md"
    assert p.exists()
    assert norm(read(p)) == expected_rules()


def test_target_both(installer, tmp_path):
    home = make_home(tmp_path)
    rc, out = run_installer(installer, "--apply", "--target", "both", "--home", str(home))
    assert rc == 0, out
    assert rules_path(home, "claude").exists()
    assert rules_path(home, "codex").exists()
    assert norm(read(rules_path(home, "claude"))) == expected_rules()
    assert norm(read(rules_path(home, "codex"))) == expected_rules()


def test_auto_env_claude(installer, tmp_path):
    home = make_home(tmp_path)
    rc, out = run_installer(installer, "--apply", "--target", "auto", "--home", str(home),
                            env_extra={"CLAUDECODE": "1"})
    assert rc == 0, out
    assert "环境变量 -> claude" in out
    assert rules_path(home, "claude").exists()
    assert not rules_path(home, "codex").exists()


def test_auto_env_codex_thread(installer, tmp_path):
    home = make_home(tmp_path)
    rc, out = run_installer(installer, "--apply", "--target", "auto", "--home", str(home),
                            env_extra={"CODEX_THREAD_ID": "t-1"})
    assert rc == 0, out
    assert "环境变量 -> codex" in out
    assert rules_path(home, "codex").exists()


def test_auto_single_host_dir(installer, tmp_path):
    home = make_home(tmp_path)
    (home / ".codex").mkdir()
    rc, out = run_installer(installer, "--dry-run", "--target", "auto", "--home", str(home))
    assert rc == 0, out
    assert "仅存在 ~/.codex" in out


def test_auto_two_host_dirs_conflict(installer, tmp_path):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    rc, out = run_installer(installer, "--apply", "--target", "auto", "--home", str(home))
    assert rc != 0
    assert "同时检测到 ~/.claude 与 ~/.codex" in out


def test_auto_no_hosts_error(installer, tmp_path):
    home = make_home(tmp_path)
    rc, out = run_installer(installer, "--apply", "--target", "auto", "--home", str(home))
    assert rc != 0
    assert "未检测到 ~/.claude 或 ~/.codex" in out


def test_backup_name_and_content(installer, tmp_path):
    home = make_home(tmp_path)
    old = "# 头部\n" + block_variant("旧版内容") + "\n尾部\n"
    write(rules_path(home), old)
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    bak = home / ".claude" / "_backup" / ("CLAUDE_" + TS + ".md.bak")
    assert bak.exists()
    assert norm(read(bak)) == old
    assert "备份" in out


def test_backup_name_collision(installer, tmp_path):
    """回归：备份重名时按 <stem>_N.<ext>.bak 递增（对齐铁律第 2 条的格式）。"""
    home = make_home(tmp_path)
    write(rules_path(home), block_variant("版本1"))
    rc, _ = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0
    write(rules_path(home), block_variant("版本2"))
    rc, _ = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0
    b1 = home / ".claude" / "_backup" / ("CLAUDE_" + TS + ".md.bak")
    b2 = home / ".claude" / "_backup" / ("CLAUDE_" + TS + "_2.md.bak")
    assert b1.exists()
    assert b2.exists()
    assert "版本1" in norm(read(b1))
    assert "版本2" in norm(read(b2))


def test_bom_rewrite(installer, tmp_path):
    home = make_home(tmp_path)
    body = "# 头部\n" + expected_rules() + "\n尾部\n"
    write(rules_path(home), b"\xef\xbb\xbf" + body.encode("utf-8"))
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "剥离 BOM" in out
    got = read(rules_path(home))
    assert got[:3] != b"\xef\xbb\xbf"
    assert norm(got) == norm(body)
    rc, out = run_installer(installer, "--verify", "--target", "claude", "--home", str(home))
    assert rc == 0, out


def test_utf8_reject(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), b"\xd6\xd0\xce\xc4 gb\n")  # GBK 字节
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "无法按 UTF-8 解码" in out


def test_symlink_rules_rejected(installer, tmp_path):
    home = make_home(tmp_path)
    real = home / "real-CLAUDE.md"
    write(real, "真实文件\n")
    link = rules_path(home)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(str(real), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("此环境无法创建符号链接")
    rc, out = run_installer(installer, "--dry-run", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "符号链接" in out


def test_extra_skill_files_and_overlap_hint(installer, tmp_path):
    home = make_home(tmp_path)
    write(home / ".claude" / "skills" / "zhuoh-code-standards" / "extra.txt", "x\n")
    write(home / ".claude" / "skills" / "code-standards" / "SKILL.md", "旧版技能\n")  # 未加前缀的旧名
    (home / ".claude" / "skills" / "coding-standards").mkdir(parents=True)
    (home / ".claude" / "skills" / "my-tool").mkdir(parents=True)
    rc, out = run_installer(installer, "--dry-run", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "目录内其他文件" in out
    assert "extra.txt" in out
    assert "现有其他 Skill" in out
    assert "coding-standards ≈ zhuoh-code-standards" in out
    assert "code-standards ≈ zhuoh-code-standards" in out
    assert "my-tool" in out


def test_marker_anomaly_error(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), expected_rules() + expected_rules())
    rc, out = run_installer(installer, "--dry-run", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "标记异常" in out


def test_skill_replace_backup(installer, tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0
    sp = home / ".claude" / "skills" / "zhuoh-code-standards" / "SKILL.md"
    modified = skill_text("zhuoh-code-standards") + "\n额外一行\n"
    write(sp, modified)
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert norm(read(sp)) == skill_text("zhuoh-code-standards")
    bak = home / ".claude" / "_backup" / "skills" / "zhuoh-code-standards" / ("SKILL_" + TS + ".md.bak")
    assert bak.exists()
    assert norm(read(bak)) == modified


def test_legacy_hint_warning(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "# 全局核心铁律（旧版手写）\n\n不可逆操作确认流程……\n")
    rc, out = run_installer(installer, "--dry-run", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "[警告]" in out
    assert "疑似已有旧版未受管铁律" in out


def test_empty_rules_file(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "")
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "规则文件为空" in out
    assert norm(read(rules_path(home))) == expected_rules()


def test_blank_rules_file(installer, tmp_path):
    home = make_home(tmp_path)
    write(rules_path(home), "\n\n\n")
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc == 0, out
    assert "仅含空白" in out
    assert norm(read(rules_path(home))) == expected_rules()
    bak = home / ".claude" / "_backup" / ("CLAUDE_" + TS + ".md.bak")
    assert bak.exists()
    assert norm(read(bak)) == "\n\n\n"


def test_apply_failure_report(installer, tmp_path):
    """--home 指向一个已存在的普通文件：创建宿主目录必然失败，须输出失败汇报。"""
    blocker = tmp_path / "blocker.txt"
    write(blocker, "x\n")
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(blocker))
    assert rc != 0
    assert "失败:" in out
    assert "未处理: 其余" in out


def test_verify_detects_tamper(installer, tmp_path):
    home = make_home(tmp_path)
    rc, _ = run_installer(installer, "--apply", "--target", "codex", "--home", str(home))
    assert rc == 0
    p = rules_path(home, "codex")
    write(p, norm(read(p)).replace("# 全局核心铁律", "# 被篡改的标题"))
    rc, out = run_installer(installer, "--verify", "--target", "codex", "--home", str(home))
    assert rc != 0
    assert "存在失败项" in out
    assert "FAIL" in out


def test_marker_inline_rejected(installer, tmp_path):
    """回归：标记不独占一行（行内有其他文字）须按标记异常停止，且不改动文件。"""
    home = make_home(tmp_path)
    old = "前缀文字 " + BEGIN + "\n旧内容\n" + END + " 后缀文字\n"
    write(rules_path(home), old)
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "标记异常" in out
    assert norm(read(rules_path(home))) == old


def test_marker_double_on_line_rejected(installer, tmp_path):
    """回归：同一行出现两个 BEGIN 须按标记异常停止（sh 曾按行计数漏判）。"""
    home = make_home(tmp_path)
    old = BEGIN + BEGIN + "\n旧内容\n" + END + "\n"
    write(rules_path(home), old)
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "标记异常" in out
    assert norm(read(rules_path(home))) == old


def test_marker_trailing_space_rejected(installer, tmp_path):
    """回归：标记行尾随空格不属于独占一行，须停止而非静默重写。"""
    home = make_home(tmp_path)
    old = BEGIN + "\n旧内容\n" + END + " \n"
    write(rules_path(home), old)
    rc, out = run_installer(installer, "--apply", "--target", "claude", "--home", str(home))
    assert rc != 0
    assert "标记异常" in out
    assert norm(read(rules_path(home))) == old


def test_missing_option_value(installer, tmp_path):
    home = make_home(tmp_path)
    rc, out = run_installer(installer, "--apply", "--home", str(home), "--target")
    assert rc != 0
    assert "缺少" in out


def test_empty_home_rejected(installer, tmp_path):
    if installer == "sh" and sys.platform == "win32":
        pytest.skip("msys 运行时会重建空 HOME，sh 的空值防护仅在真实 POSIX 环境可触发")
    if installer == "ps1":
        pytest.skip("Windows PowerShell 5.1 在 USERPROFILE 为空时启动即崩溃；同一防护由 pwsh 驱动覆盖")
    rc, out = run_installer(installer, "--dry-run", "--target", "claude",
                            env_extra={"HOME": "", "USERPROFILE": ""})
    assert rc != 0
    assert "未设置" in out
