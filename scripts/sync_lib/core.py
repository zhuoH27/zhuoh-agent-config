# -*- coding: utf-8 -*-
"""基础工具、配置加载、宿主探测、原子写入与分层备份。"""
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

VERSION = "3.4.0"
BEGIN_MARK = "<!-- BEGIN: global-iron-rules -->"
END_MARK = "<!-- END: global-iron-rules -->"
TS_RE = re.compile(r"^\d{8}_\d{6}$")


def die(msg, code=1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def configure_stdio():
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def ts_now():
    v = os.environ.get("AGENT_CONFIG_TS", "")
    return v if TS_RE.match(v) else time.strftime("%Y%m%d_%H%M%S")


def expand_user(p, home):
    s = str(p)
    if s == "~":
        return home
    if s.startswith("~/") or s.startswith("~\\"):
        return home / s[2:]
    return Path(s)


def home_base(args_home):
    if args_home:
        return expand_user(args_home, Path.home()).resolve()
    h = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not h:
        die("HOME/USERPROFILE 未设置，无法定位宿主目录；请设置或用 --home 指定")
    return Path(h).resolve()


def norm_text(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return str(raw).replace("\r\n", "\n").replace("\r", "\n")


def read_utf8(path):
    try:
        return Path(path).read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as e:
        die(f"{path} 无法按 UTF-8 解码，请先转换为 UTF-8（{e}）")


def sha256_norm(path):
    try:
        return hashlib.sha256(norm_text(Path(path).read_bytes()).encode("utf-8")).hexdigest()
    except OSError:
        return None


def sha256_raw(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def detect_eol(text):
    return "\r\n" if "\r\n" in text else "\n"


def atomic_write(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".agent_tmp")
    tmp.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    os.replace(tmp, p)


def points_to(target, src):
    try:
        return Path(os.path.realpath(target)) == Path(os.path.realpath(src))
    except OSError:
        return False


def make_backup(root, path, ts, *, host_key=None, host_root=None,
                dry_run=False, planned=None):
    """分层备份：~/.zhuoh-agent-backup/<TS>/<host>/<相对目录>/<原名>_<TS><ext>.bak。

    若提供 planned 集合（dry-run 阶段），同步记录已规划路径，保证预览与落盘重名后缀一致。
    """
    p = Path(path)
    stem = p.stem if p.suffix else p.name
    base_dir = Path(root) / ts
    if host_key:
        base_dir = base_dir / host_key
        if host_root is not None:
            try:
                rel_parent = p.resolve().parent.relative_to(Path(host_root).resolve())
                if str(rel_parent) not in ("", "."):
                    base_dir = base_dir / rel_parent
            except (ValueError, OSError):
                pass

    def _taken(candidate):
        return candidate.exists() or (planned is not None and candidate in planned)

    cand = base_dir / f"{stem}_{ts}{p.suffix}.bak"
    n = 2
    while _taken(cand):
        cand = base_dir / f"{stem}_{ts}_{n}{p.suffix}.bak"
        n += 1
    if planned is not None:
        planned.add(cand)
    if not dry_run:
        cand.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, cand)
    return cand


class Manifest:
    def __init__(self, repo):
        try:
            data = json.loads((Path(repo) / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            die(f"manifest.json 解析失败: {e}")
        self.backup_root_name = data.get("backup_root", "~/.zhuoh-agent-backup")
        self.default_mode = data.get("default_mode", "copy")
        if self.default_mode not in ("copy", "link"):
            die(f"manifest default_mode 非法: {self.default_mode}")
        self.hosts = data.get("hosts", {})
        self.overlaps = data.get("known_overlaps", {})
        sources = data.get("sources", {})
        self.rules_src = sources.get("rules", "AGENTS.md")
        self.skills_src = sources.get("skills", "skills")
        self.prompts_src = sources.get("prompts", "prompts")
        if not self.hosts:
            die("manifest hosts 为空")

    def host_root(self, key, home):
        return expand_user(self.hosts[key]["root"], home)

    def rules_path(self, key, home):
        c = self.hosts[key]
        return self.host_root(key, home) / c.get("rules_target", "AGENTS.md")

    def skills_dir(self, key, home):
        c = self.hosts[key]
        return self.host_root(key, home) / c.get("skills_dir", "skills")

    def prompts_dir(self, key, home):
        c = self.hosts[key]
        pd = c.get("prompts_dir", "")
        return self.host_root(key, home) / pd if pd else None

    def backup_root(self, home):
        return expand_user(self.backup_root_name, home)


def resolve_targets(target_arg, mf, home, env=None):
    env = os.environ if env is None else env
    known = list(mf.hosts)
    if target_arg == "auto":
        if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
            return ["claude"], "环境变量 -> claude"
        if env.get("CODEX_THREAD_ID"):
            return ["codex"], "环境变量 -> codex"
        existing = [k for k in known if mf.host_root(k, home).exists()]
        if len(existing) > 1:
            die(f"检测到多个宿主（{'、'.join(existing)}），无法唯一确定，请用 --target 明确指定。")
        if len(existing) == 1:
            k = existing[0]
            label = {"claude": "仅存在 ~/.claude", "codex": "仅存在 ~/.codex"}.get(
                k, f"仅存在 {mf.hosts[k]['root']}"
            )
            return [k], label
        die("未检测到 ~/.claude、~/.codex 或 ~/.agents，请用 --target 明确指定（可先创建对应目录）。")
    if target_arg == "both":
        return ["claude", "codex"], "both"
    if target_arg in known:
        return [target_arg], target_arg
    die(f"未知 --target: {target_arg}")


def skill_dirs(repo, skills_rel="skills"):
    src = Path(repo) / skills_rel
    return sorted(d for d in src.iterdir() if d.is_dir()) if src.is_dir() else []


def try_link(src, tgt, is_dir):
    """优先 symlink，Windows 目录降级 junction；失败返回 None。"""
    tgt.parent.mkdir(parents=True, exist_ok=True)
    if tgt.is_symlink() or (is_dir and tgt.exists() and points_to(tgt, src)):
        return tgt if points_to(tgt, src) else None
    if tgt.exists():
        return None
    try:
        os.symlink(str(Path(src).resolve()), str(tgt), target_is_directory=is_dir)
        return tgt
    except OSError:
        pass
    if os.name == "nt" and is_dir:
        try:
            import _winapi
            _winapi.CreateJunction(str(Path(src).resolve()), str(tgt))
            return tgt
        except (OSError, ImportError):
            return None
    return None
