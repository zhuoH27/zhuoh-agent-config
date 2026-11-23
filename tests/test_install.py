"""install.py 的单元与集成测试。

全部通过 --home 指向临时目录运行，不触碰真实 ~/.claude / ~/.codex / ~/.agents。
运行：python -m unittest discover -s tests -v
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "install.py"
sys.path.insert(0, str(REPO))
import install  # noqa: E402


def run_install(args, home):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--home", str(home)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


class BaseHome(unittest.TestCase):
    """带临时 home（含 ~/.codex/AGENTS.md 占位目录）的用例基类。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.rules = self.home / ".codex" / "AGENTS.md"
        self.rules.parent.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_(self, *args):
        return run_install(list(args), self.home)

    def write_rules(self, data: bytes):
        self.rules.write_bytes(data)

    def source_rules_bytes(self) -> bytes:
        return (REPO / "AGENTS.md").read_bytes()


class TestHelpers(unittest.TestCase):
    def test_backup_filename(self):
        self.assertEqual(
            install.backup_filename("AGENTS.md", "20260101_000000"),
            "AGENTS_20260101_000000.md.bak",
        )
        self.assertEqual(install.backup_filename("README", "t"), "README_t.bak")

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.txt"
            p.write_text("x", encoding="utf-8")
            self.assertEqual(install.unique_path(p), p.with_name("a_2.txt"))

    def test_extract_block_ok(self):
        text = "前\n" + install.BEGIN_MARK + "\n内容\n" + install.END_MARK + "\n后"
        block = install.extract_block(text)
        self.assertIn("内容", block)
        self.assertTrue(block.startswith(install.BEGIN_MARK))
        self.assertTrue(block.endswith(install.END_MARK))

    def test_extract_block_broken(self):
        with self.assertRaises(ValueError):
            install.extract_block("没有标记")

    def test_read_text_keeps_crlf(self):  # B1：读取不得丢失 CRLF
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_bytes(b"a\r\nb\r\n")
            self.assertIn("\r\n", install.read_text(p))

    def test_read_text_bom_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_bytes(b"\xef\xbb\xbfabc")
            self.assertEqual(install.read_text(p), "abc")

    def test_read_text_gbk_clean_error(self):  # B2：可读报错而非 traceback
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_bytes("中文".encode("gbk"))
            with self.assertRaises(SystemExit) as ctx:
                install.read_text(p)
            self.assertIn("无法按 UTF-8 解码", str(ctx.exception))

    def test_source_rules_is_block_only(self):  # B4/N2：源只取受管区块
        text = install.load_source_rules()
        self.assertTrue(text.startswith(install.BEGIN_MARK))
        self.assertTrue(text.endswith(install.END_MARK))
        self.assertNotIn("# agent-config", text)

    def test_host_for(self):
        h = install.host_for("agents", Path("/h"))
        self.assertEqual(h.rules, Path("/h/.agents/AGENTS.md"))
        h2 = install.host_for("claude", Path("/h"))
        self.assertEqual(h2.rules, Path("/h/.claude/CLAUDE.md"))

    def test_resolve_targets_both(self):
        hosts = install.resolve_targets("both", Path("/h"))
        self.assertEqual([h.key for h in hosts], ["claude", "codex"])


class TestInstall(BaseHome):
    def test_fresh_install_and_idempotent(self):
        r = self.run_("--apply", "--target", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.rules.is_file())
        self.assertFalse(self.rules.read_bytes().startswith(b"\xef\xbb\xbf"))
        skill = self.home / ".codex" / "skills" / "code-standards" / "SKILL.md"
        self.assertNotIn(b"\r\n", skill.read_bytes())
        v = self.run_("--verify", "--target", "codex")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        r2 = self.run_("--apply", "--target", "codex")
        self.assertEqual(r2.returncode, 0)
        self.assertIn("跳过", r2.stdout)

    def test_append_keeps_user_content_and_backs_up(self):
        self.write_rules("# 我的内容\n".encode("utf-8"))
        r = self.run_("--apply", "--target", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        raw = self.rules.read_bytes()
        self.assertTrue(raw.startswith("# 我的内容\n".encode("utf-8")))
        self.assertIn(install.BEGIN_MARK.encode("utf-8"), raw)
        backups = list((self.home / ".codex" / "_backup").glob("AGENTS_*"))
        self.assertEqual(len(backups), 1)

    def test_crlf_preserved_on_append(self):  # B1：整文件不得被转成 LF
        self.write_rules(b"# mine\r\nline2\r\n")
        r = self.run_("--apply", "--target", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        raw = self.rules.read_bytes()
        self.assertGreater(raw.count(b"\r\n"), 0)
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))

    def test_crlf_preserved_on_block_replace(self):  # B1：区块外内容不动
        stale = (
            self.source_rules_bytes()
            .decode("utf-8-sig")
            .replace("全局核心铁律", "全局核心铁律（旧）")
            .replace("\n", "\r\n")
        )
        self.write_rules(("头部\r\n" + stale + "尾部\r\n").encode("utf-8"))
        r = self.run_("--apply", "--target", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        raw = self.rules.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertTrue(raw.startswith("头部\r\n".encode("utf-8")))
        self.assertIn("尾部\r\n".encode("utf-8"), raw)
        self.assertNotIn("（旧）".encode("utf-8"), raw)
        v = self.run_("--verify", "--target", "codex")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)

    def test_gbk_file_clean_error(self):  # B2
        self.write_rules("中文内容".encode("gbk"))
        r = self.run_("--dry-run", "--target", "codex")
        self.assertNotEqual(r.returncode, 0)
        combined = r.stdout + r.stderr
        self.assertNotIn("Traceback", combined)
        self.assertIn("无法按 UTF-8 解码", combined)

    def test_broken_markers_no_write(self):
        self.write_rules((install.BEGIN_MARK + "\n孤立标记\n").encode("utf-8"))
        before = self.rules.read_bytes()
        r = self.run_("--apply", "--target", "codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.rules.read_bytes(), before)

    def test_legacy_rules_warning(self):  # B3：疑似旧版铁律时警告
        self.write_rules("# 旧版\n全局核心铁律（旧版文字）\n".encode("utf-8"))
        r = self.run_("--dry-run", "--target", "codex")
        self.assertEqual(r.returncode, 0)
        self.assertIn("[警告]", r.stdout)

    def test_mode_abort(self):
        self.write_rules("# 用户内容\n".encode("utf-8"))
        r = self.run_("--dry-run", "--target", "codex", "--mode", "abort")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("abort", r.stdout + r.stderr)

    def test_bom_rewrite_when_up_to_date(self):  # N1：skip+BOM 死锁修复
        self.write_rules(b"\xef\xbb\xbf" + self.source_rules_bytes())
        r = self.run_("--apply", "--target", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("剥离 BOM", r.stdout)
        self.assertFalse(self.rules.read_bytes().startswith(b"\xef\xbb\xbf"))
        v = self.run_("--verify", "--target", "codex")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)

    def test_dryrun_shows_diff_for_stale_block(self):  # 区块 diff
        stale = self.source_rules_bytes().decode("utf-8-sig").replace(
            "不可逆操作确认", "不可逆操作确认（改）"
        )
        self.write_rules(stale.encode("utf-8"))
        r = self.run_("--dry-run", "--target", "codex")
        self.assertEqual(r.returncode, 0)
        self.assertIn("replace_block", r.stdout)
        self.assertIn("--- 已安装", r.stdout)
        self.assertIn("+++ 仓库", r.stdout)

    def test_verify_catches_stale_rules_block(self):
        self.run_("--apply", "--target", "codex")
        text = self.rules.read_bytes().decode("utf-8-sig")
        self.write_rules(text.replace("全局核心铁律", "全局核心铁律（改）").encode("utf-8"))
        v = self.run_("--verify", "--target", "codex")
        self.assertNotEqual(v.returncode, 0)

    def test_verify_catches_wrong_skill_name(self):  # B5
        self.run_("--apply", "--target", "codex")
        skill = self.home / ".codex" / "skills" / "code-standards" / "SKILL.md"
        text = skill.read_bytes().decode("utf-8-sig")
        skill.write_bytes(text.replace("name: code-standards", "name: wrong").encode("utf-8"))
        v = self.run_("--verify", "--target", "codex")
        self.assertNotEqual(v.returncode, 0)
        self.assertIn("name", v.stdout)

    def test_verify_catches_multiline_description(self):  # B5
        self.run_("--apply", "--target", "codex")
        skill = self.home / ".codex" / "skills" / "code-standards" / "SKILL.md"
        text = skill.read_bytes().decode("utf-8-sig")
        new_text = re.sub(r"^description: .*$", "description: >", text, count=1, flags=re.M)
        skill.write_bytes(new_text.encode("utf-8"))
        v = self.run_("--verify", "--target", "codex")
        self.assertNotEqual(v.returncode, 0)
        self.assertIn("description", v.stdout)

    def test_symlink_rejected(self):
        try:
            real = self.home / "real.md"
            real.write_text("x", encoding="utf-8")
            self.rules.symlink_to(real)
        except OSError:
            self.skipTest("当前环境无法创建符号链接")
        r = self.run_("--dry-run", "--target", "codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("符号链接", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
