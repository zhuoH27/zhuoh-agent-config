#!/bin/sh
# agent-config 极简入口（POSIX sh）。核心逻辑在 scripts/agent_sync.py（Python 3 标准库）。
# 有 Python：透传全部参数（--verify 映射为 doctor）。
# 无 Python：裸机兜底，纯拷贝 AGENTS.md 与 skills/ 到宿主（备份后覆盖，功能受限）。
# 兼容原 v2.2.0 参数：[--dry-run|--apply|--verify] --target auto|claude|codex|agents|both
#                     --mode append|replace|abort --home 目录 --version
# 安全边界：无网络访问；不执行任意代码；备份统一存 ~/.zhuoh-agent-backup/<TS>/。

VERSION='3.0.0'
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || { printf '%s\n' '无法定位脚本所在目录' >&2; exit 1; }

[ "$1" = '--version' ] && { printf 'agent-config %s (sh)\n' "$VERSION"; exit 0; }

# 定位 Python（跳过 Microsoft Store 的 python3 存根别名）
PY=''
for c in python python3; do
    if command -v "$c" >/dev/null 2>&1; then
        if "$c" -c 'import sys' >/dev/null 2>&1; then PY=$c; break; fi
    fi
done

if [ -n "$PY" ]; then
    # --verify 语义映射到 doctor；--dry-run/--apply/--mode/--target/--home 透传
    sub=setup
    pass=''
    while [ $# -gt 0 ]; do
        case "$1" in
            --verify) sub=doctor ;;
            --apply) ;;  # setup 默认即 apply
            *) pass="$pass $1" ;;
        esac
        shift
    done
    exec "$PY" -I "$REPO/scripts/agent_sync.py" "$sub" $pass
fi

# --- 裸机兜底（无 Python）---
printf '%s\n' '未检测到 Python，使用裸机兜底模式（纯拷贝，功能受限）。'

TS=$(date +%Y%m%d_%H%M%S)
target=auto
home=${HOME:-}
[ -n "$home" ] || { printf '%s\n' 'HOME 未设置' >&2; exit 1; }
BROOT=$home/.zhuoh-agent-backup/$TS
mkdir -p "$BROOT" || { printf '无法创建备份目录: %s\n' "$BROOT" >&2; exit 1; }

# 解析 --target / --home
while [ $# -gt 0 ]; do
    case "$1" in
        --target) [ $# -ge 2 ] || { printf '%s\n' '缺少 --target 的值' >&2; exit 1; }
                  target=$2; shift 2 ;;
        --home)   [ $# -ge 2 ] || { printf '%s\n' '缺少 --home 的值' >&2; exit 1; }
                  case $2 in ~*) home=$home${2#\~} ;; *) home=$2 ;; esac; shift 2 ;;
        --dry-run) printf '%s\n' '兜底模式不支持 --dry-run，请安装 Python 后使用完整功能。' >&2; exit 1 ;;
        --mode|abort) printf '%s\n' '兜底模式不支持 --mode，默认整文件替换。' >&2 ;;
        *) shift ;;
    esac
done

copy_host() {
    key=$1
    root=$home/.$key
    rules=$root/AGENTS.md
    [ "$key" = claude ] && rules=$root/CLAUDE.md
    mkdir -p "$root/skills" || return 1
    if [ -f "$rules" ]; then
        ext=$(printf '%s\n' "$rules" | sed -n 's/.*\.\([^./]*\)$/\1/p')
        bak=$BROOT/$(basename "$rules" .md)_$TS.${ext:-md}.bak
        cp "$rules" "$bak" || return 1
        printf '备份: %s -> %s\n' "$rules" "$bak"
    fi
    cp "$REPO/AGENTS.md" "$rules" || return 1
    printf '写入: %s\n' "$rules"
    for d in "$REPO"/skills/*/; do
        [ -d "$d" ] || continue
        name=$(basename "$d")
        if [ -f "$root/skills/$name/SKILL.md" ]; then
            cp "$root/skills/$name/SKILL.md" "$BROOT/SKILL_${name}_$TS.md.bak" || return 1
            rm -rf "$root/skills/$name"
        fi
        cp -r "$d" "$root/skills/$name" || return 1
        printf 'Skill: %s\n' "$root/skills/$name"
    done
}

case $target in
    claude|codex|agents) hosts=$target ;;
    both) hosts='claude codex' ;;
    auto)
        c=0
        [ -d "$home/.claude" ] && c=$((c+1))
        [ -d "$home/.codex" ] && c=$((c+1))
        [ "$c" -gt 1 ] && { printf '%s\n' '同时检测到 ~/.claude 与 ~/.codex，请用 --target 明确指定。' >&2; exit 1; }
        [ "$c" -eq 0 ] && { printf '%s\n' '未检测到 ~/.claude 或 ~/.codex，请用 --target 明确指定。' >&2; exit 1; }
        [ -d "$home/.claude" ] && hosts=claude || hosts=codex
        ;;
    *) printf '未知 --target: %s\n' "$target" >&2; exit 1 ;;
esac

for h in $hosts; do
    copy_host "$h" || exit 1
done
printf '完成（兜底模式）。备份在 %s\n' "$BROOT"
