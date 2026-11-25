# -*- coding: utf-8 -*-
"""发布一致性检查：VERSION 与 HEAD 上的 tag 是否对应。

提示性工具（CI 中 continue-on-error），不匹配时输出说明而非失败。
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORE = REPO / "scripts" / "sync_lib" / "core.py"


def main():
    m = re.search(r'^VERSION = "([^"]+)"', CORE.read_text(encoding="utf-8"), re.M)
    if not m:
        print("[FAIL] core.py 未找到 VERSION 常量")
        sys.exit(1)
    version = m.group(1)
    r = subprocess.run(["git", "tag", "--points-at", "HEAD"], cwd=str(REPO),
                       capture_output=True, text=True)
    tags = [t.strip() for t in (r.stdout or "").splitlines() if t.strip()]
    expected = [f"v{version}"]
    if not tags:
        print(f"[提示] HEAD 无 tag；当前版本 {version} 未发布固定版本。")
        print(f"       发布：git tag v{version} && git push origin v{version}（tag 与 VERSION 同号）")
        return
    if any(t in expected for t in tags):
        print(f"[OK] HEAD tag {tags} 与 VERSION {version} 一致。")
        return
    print(f"[提示] HEAD tag {tags} 与 VERSION {version} 不一致（期望 v{version}）。")
    print("       若刚提升版本号，请 git tag v{version} 并推送；或检查是否漏改 VERSION。")


if __name__ == "__main__":
    main()
