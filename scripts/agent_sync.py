# -*- coding: utf-8 -*-
"""agent-config 核心同步引擎 CLI 入口（Windows 平台，Python 3 标准库，无外部依赖）。

命令面：setup / doctor / audit / status。
具体实现拆分为 scripts/sync_lib/ 下的 core、sync、audit 三个职责单一模块。
"""
import argparse
import sys
from pathlib import Path

# 兼容 `python -I` 隔离模式（隔离模式不把脚本目录加入 sys.path）
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from sync_lib.audit import cmd_audit  # noqa: E402
from sync_lib.core import VERSION, configure_stdio  # noqa: E402
from sync_lib.sync import cmd_doctor, cmd_setup, cmd_status  # noqa: E402

DEFAULT_REPO = Path(__file__).resolve().parent.parent


def main(argv=None):
    configure_stdio()
    ap = argparse.ArgumentParser(prog="agent_sync", description="agent-config 同步引擎")
    ap.add_argument("--version", action="version", version=f"agent-config {VERSION}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="覆盖仓库根（测试沙盒用）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_target_parser(name, **kw):
        parser = sub.add_parser(name, parents=[common], **kw)
        parser.add_argument("--target", default="auto")
        parser.add_argument("--home")
        return parser

    p_setup = add_target_parser("setup", help="一键初始化/覆盖更新")
    p_setup.add_argument("--dry-run", action="store_true")
    p_setup.add_argument("--apply", action="store_true", help="兼容旧入口：setup 默认即执行")
    p_setup.add_argument("--mode", choices=["append", "replace", "abort"], help="规则文件合并模式")
    p_setup.add_argument("--skill-mode", choices=["copy", "link"], help="Skill 安装模式")
    p_setup.set_defaults(func=cmd_setup)

    p_doctor = add_target_parser("doctor", help="健康体检")
    p_doctor.set_defaults(func=cmd_doctor)

    p_audit = sub.add_parser("audit", parents=[common], help="安全与规范门禁")
    p_audit.set_defaults(func=cmd_audit)

    p_status = sub.add_parser("status", parents=[common], help="状态摘要")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--home")
    p_status.set_defaults(func=cmd_status)

    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve() if getattr(args, "repo", None) else DEFAULT_REPO
    args.func(args, repo)


if __name__ == "__main__":
    main()
