#!/bin/sh
# agent-config 安装器（POSIX sh 版，供 macOS/Linux 及含 sh 的环境使用）。
# 依赖：POSIX sh 与常规系统工具（awk/sed/grep/tr/cmp/diff/dd/tail/head/wc/cat/cp/mv/mkdir/date/mktemp/iconv）。
# 安全边界：无网络访问；不执行任意代码；只读写宿主规则文件、skills/*/SKILL.md 与 _backup/；
# 写入前先备份；写入走同目录临时文件+原子改名。AGENT_CONFIG_TS 仅供测试固定时间戳。
# 用法：sh install.sh [--dry-run|--apply|--verify] [--target auto|claude|codex|agents|both] [--mode append|replace|abort] [--home 目录]

VERSION='2.1.0'
BEGIN_MARK='<!-- BEGIN: global-iron-rules -->'
END_MARK='<!-- END: global-iron-rules -->'
SKILL_NAMES='zhuoh-code-standards zhuoh-ppt-maker zhuoh-paper-writing zhuoh-idea-evaluation'
TS_HINT='YYYYMMDD_HHMMSS'
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || { printf '%s\n' '无法定位脚本所在目录' >&2; exit 1; }
WORK=$(mktemp -d) || { printf '%s\n' '无法创建临时目录' >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
REAL_HOME=${HOME:-}
W_WRITTEN=$WORK/.written
W_BACKUPS=$WORK/.backups
W_SKIPPED=$WORK/.skipped
: > "$W_WRITTEN"; : > "$W_BACKUPS"; : > "$W_SKIPPED"

die() { printf '%b\n' "$*" >&2; exit 1; }

ts_now() {
    if [ -n "$AGENT_CONFIG_TS" ]; then printf '%s\n' "$AGENT_CONFIG_TS"; else date +%Y%m%d_%H%M%S; fi
}

has_bom() {
    [ "$(dd if="$1" bs=1 count=3 2>/dev/null)" = "$(printf '\357\273\277')" ]
}

# 读取：剥离 BOM 并按严格 UTF-8 校验；非 UTF-8 文件以可读错误停止
decode() { # $1=源文件 $2=输出文件
    if has_bom "$1"; then
        tail -c +4 "$1" > "$2" || die "读取失败: $1"
    else
        cat "$1" > "$2" || die "读取失败: $1"
    fi
    if ! iconv -f UTF-8 -t UTF-8 < "$2" > "$WORK/.conv" 2>/dev/null; then
        die "无法按 UTF-8 解码 $1。若文件是 GBK/UTF-16 等编码，请先转成 UTF-8 再运行；脚本不猜测编码。"
    fi
    mv -f "$WORK/.conv" "$2"
}

# 注意：部分环境（如 Git Bash）的 sed/awk/grep 读文件时会剥掉 \r（管道则字节安全），
# 故本脚本对字节敏感路径只用 cat/head/tail/tr/dd/iconv/cmp 等字节安全工具。
is_crlf() { tr -d -c '\r' < "$1" 2>/dev/null | grep -q .; }

extract_block() { # BEGIN 行到 END 行，逐行原样输出
    awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
        !on && index($0, b) { on = 1 }
        on { print }
        on && index($0, e) { exit }
    ' "$1"
}

marker_count() { grep -c -F "$1" "$2" 2>/dev/null; }
line_no() { awk -v s="$1" 'index($0, s) { print NR; exit }' "$2"; }

same_normalized() {
    tr -d '\r' < "$1" > "$WORK/.n1"
    tr -d '\r' < "$2" > "$WORK/.n2"
    cmp -s "$WORK/.n1" "$WORK/.n2"
}

block_nl() { # $1=区块文件 $2=输出文件 $3=crlf(1/0)，每行补终结符
    tr -d '\r' < "$1" > "$WORK/.bn"
    if [ "$3" = "1" ]; then
        awk -v cr="$(printf '\r')" '{ printf "%s%s\n", $0, cr }' "$WORK/.bn" > "$2"
    else
        awk '{ print }' "$WORK/.bn" > "$2"
    fi
}

load_source_rules() {
    [ -f "$REPO/AGENTS.md" ] || die "缺少源规则文件: $REPO/AGENTS.md"
    decode "$REPO/AGENTS.md" "$WORK/source_all"
    bc=$(marker_count "$BEGIN_MARK" "$WORK/source_all")
    ec=$(marker_count "$END_MARK" "$WORK/source_all")
    [ "$bc" = "1" ] && [ "$ec" = "1" ] || die "源 AGENTS.md 的受管标记不成对"
    bl=$(line_no "$BEGIN_MARK" "$WORK/source_all")
    el=$(line_no "$END_MARK" "$WORK/source_all")
    [ "$el" -ge "$bl" ] || die "源 AGENTS.md 的 END 在 BEGIN 之前"
    extract_block "$WORK/source_all" > "$WORK/source_block"
    for name in $SKILL_NAMES; do
        decode "$REPO/skills/$name/SKILL.md" "$WORK/src_$name"
    done
}

set_host() {
    HOST_KEY=$1
    HOST_ROOT=$HOME_BASE/.$1
    case $1 in
        claude) HOST_LABEL='Claude Code'; HOST_RULES=$HOST_ROOT/CLAUDE.md ;;
        codex) HOST_LABEL='Codex CLI'; HOST_RULES=$HOST_ROOT/AGENTS.md ;;
        agents) HOST_LABEL='~/.agents 约定'; HOST_RULES=$HOST_ROOT/AGENTS.md ;;
        *) die "未知宿主: $1" ;;
    esac
    HOST_SKILLS=$HOST_ROOT/skills
}

backup_name() { # $1=文件名 $2=时间戳
    case $1 in
        *.*) printf '%s_%s.%s.bak\n' "${1%.*}" "$2" "${1##*.}" ;;
        *) printf '%s_%s.bak\n' "$1" "$2" ;;
    esac
}

unique_dest() { # $1=期望备份路径（已存在时依次加 _2、_3）
    if [ ! -e "$1" ]; then printf '%s\n' "$1"; return 0; fi
    dir=$(dirname -- "$1")
    leaf=$(basename -- "$1")
    base=${leaf%.bak}
    stem=$base
    ext=''
    case $base in
        *.*) stem=${base%.*}; ext=${base##*.} ;;
    esac
    n=2
    while :; do
        if [ -n "$ext" ]; then
            cand="$dir/$(printf '%s_%s.%s.bak' "$stem" "$n" "$ext")"
        else
            cand="$dir/$(printf '%s_%s.bak' "$stem" "$n")"
        fi
        [ ! -e "$cand" ] && break
        n=$((n + 1))
    done
    printf '%s\n' "$cand"
}

do_backup() { # $1=期望备份路径 $2=源文件；输出实际备份路径
    mkdir -p -- "$(dirname -- "$1")" || return 1
    dest=$(unique_dest "$1")
    cp -p -- "$2" "$dest" || return 1
    printf '%s\n' "$dest"
}

atomic_install() { # $1=内容文件 $2=目标（同目录临时文件+原子改名）
    mkdir -p -- "$(dirname -- "$2")" || return 1
    tmp=$(dirname -- "$2")/.$(basename -- "$2").tmp.$$
    cat -- "$1" > "$tmp" || { rm -f -- "$tmp"; return 1; }
    mv -f -- "$tmp" "$2" || { rm -f -- "$tmp"; return 1; }
    return 0
}

ends_with_newline() { # $1=文件
    lf=$(wc -l < "$1" | tr -d ' ')
    recs=$(awk 'END { print NR }' "$1")
    [ "$recs" -gt 0 ] && [ "$lf" -eq "$recs" ]
}

plan_rules() { # $1=mode；设置 RULES_* 全局
    RULES_ACTION='' RULES_REASON='' RULES_BACKUP='' RULES_BL=0 RULES_EL=0
    target=$HOST_RULES
    [ -L "$target" ] && die "规则文件是符号链接，拒绝写入: $target"
    if [ ! -e "$target" ]; then
        RULES_ACTION=create; RULES_REASON='规则文件不存在，将新建'; return 0
    fi
    decode "$target" "$WORK/old_rules"
    size=$(wc -c < "$target" | tr -d ' ')
    bc=$(marker_count "$BEGIN_MARK" "$WORK/old_rules")
    ec=$(marker_count "$END_MARK" "$WORK/old_rules")
    RULES_BL=$(line_no "$BEGIN_MARK" "$WORK/old_rules")
    RULES_EL=$(line_no "$END_MARK" "$WORK/old_rules")
    if [ "$bc" = "1" ] && [ "$ec" = "1" ] && [ "$RULES_EL" -ge "$RULES_BL" ]; then
        extract_block "$WORK/old_rules" > "$WORK/old_block"
        if same_normalized "$WORK/old_block" "$WORK/source_block"; then
            if has_bom "$target"; then
                RULES_ACTION=rewrite
                RULES_REASON='受管区块已是最新，但文件带 BOM；将备份后原样重写（仅剥离 BOM）'
                RULES_BACKUP=$HOST_ROOT/_backup/$(backup_name "$(basename -- "$target")" "$TS_HINT")
            else
                RULES_ACTION=skip; RULES_REASON='受管区块已是最新'
            fi
            return 0
        fi
        RULES_ACTION=replace_block
        RULES_REASON='将替换受管区块'
        RULES_BACKUP=$HOST_ROOT/_backup/$(backup_name "$(basename -- "$target")" "$TS_HINT")
        return 0
    fi
    if [ "$bc" != "0" ] || [ "$ec" != "0" ]; then
        die "标记异常: $target (BEGIN=$bc, END=$ec)；请先手动修复，脚本不自动修"
    fi
    if [ "$size" -eq 0 ]; then
        RULES_ACTION=create; RULES_REASON='规则文件为空，将写入'; return 0
    fi
    RULES_BACKUP=$HOST_ROOT/_backup/$(backup_name "$(basename -- "$target")" "$TS_HINT")
    if [ -z "$(tr -d '[:space:]' < "$WORK/old_rules")" ]; then
        RULES_ACTION=replace_file; RULES_REASON='规则文件仅含空白，备份后写入'; return 0
    fi
    if [ "$1" = 'abort' ]; then
        die "$target 已有内容但没有受管标记；按 --mode abort 停止"
    fi
    if [ "$1" = 'replace' ]; then
        RULES_ACTION=replace_file; RULES_REASON='按 --mode replace 整文件替换'; return 0
    fi
    RULES_ACTION=append
    RULES_REASON='已有内容无标记，将追加受管区块（保留原内容）'
    if grep -q -F '全局核心铁律' "$WORK/old_rules" || grep -q -F '不可逆操作确认' "$WORK/old_rules"; then
        RULES_REASON="$RULES_REASON；[警告] 疑似已有旧版未受管铁律，直接追加会重复或冲突，请人工合并，或经用户确认后改用 --mode replace"
    fi
    return 0
}

plan_skill() { # $1=skill 名；设置 SK_* 全局
    SK_ACTION='' SK_REASON='' SK_BACKUP='' SK_OTHERS=''
    target=$HOST_SKILLS/$1/SKILL.md
    [ -L "$target" ] && die "Skill 文件是符号链接，拒绝写入: $target"
    d=$(dirname -- "$target")
    if [ -d "$d" ]; then
        for f in "$d"/*; do
            [ -f "$f" ] || continue
            b=$(basename -- "$f")
            [ "$b" = 'SKILL.md' ] || SK_OTHERS="$SK_OTHERS$b "
        done
    fi
    if [ ! -e "$target" ]; then
        SK_ACTION=create; SK_REASON='将新建'; return 0
    fi
    decode "$target" "$WORK/old_skill_$1"
    if same_normalized "$WORK/old_skill_$1" "$WORK/src_$1"; then
        SK_ACTION=skip; SK_REASON='已是最新'
    else
        SK_ACTION=replace; SK_REASON='将备份后覆盖 SKILL.md'
        SK_BACKUP=$HOST_ROOT/_backup/skills/$1/$(backup_name 'SKILL.md' "$TS_HINT")
    fi
    return 0
}

overlap_for() {
    case $1 in
        coding-standards) printf 'zhuoh-code-standards\n' ;;
        academic-pptx|nature-paper2ppt|scientific-figure-making) printf 'zhuoh-ppt-maker\n' ;;
        anti-defensive-writing) printf 'zhuoh-paper-writing\n' ;;
        code-standards|ppt-maker|paper-writing|idea-evaluation) printf 'zhuoh-%s\n' "$1" ;;
        *) return 1 ;;
    esac
}

print_plan() {
    printf '\n宿主: %s (%s)\n' "$HOST_LABEL" "$HOST_KEY"
    printf '  根目录: %s\n' "$HOST_ROOT"
    printf '  规则文件: %s\n' "$HOST_RULES"
    printf '  Skills 目录: %s\n' "$HOST_SKILLS"
    printf '  规则处理: %s - %s\n' "$RULES_ACTION" "$RULES_REASON"
    [ -n "$RULES_BACKUP" ] && printf '    将备份到: %s\n' "$RULES_BACKUP"
    if [ "$RULES_ACTION" = 'replace_block' ]; then
        d=$(diff "$WORK/.n1" "$WORK/.n2" | wc -l | tr -d ' ')
        printf '    区块差异（diff 摘要，共约 %s 行）:\n' "$d"
        diff "$WORK/.n1" "$WORK/.n2" | head -n 8 | sed 's/^/    /'
    fi
    for name in $SKILL_NAMES; do
        plan_skill "$name"
        printf '  Skill %s: %s - %s\n' "$name" "$SK_ACTION" "$SK_REASON"
        [ -n "$SK_BACKUP" ] && printf '    将备份到: %s\n' "$SK_BACKUP"
        others=${SK_OTHERS% }
        [ -n "$others" ] && printf '    目录内其他文件（不会改动）: %s\n' "$others"
    done
    if [ -d "$HOST_SKILLS" ]; then
        found=''
        for d in "$HOST_SKILLS"/*; do
            [ -d "$d" ] || continue
            b=$(basename -- "$d")
            case " $SKILL_NAMES " in *" $b "*) continue ;; esac
            found="$found $b"
        done
        if [ -n "$found" ]; then
            printf '  现有其他 Skill（不会改动）:%s\n' "$found"
            ov=''
            for b in $found; do
                if m=$(overlap_for "$b"); then ov="$ov $b ≈ $m"; fi
            done
            [ -n "$ov" ] && printf '  可能功能重叠（仅提醒，不删除）:%s\n' "$ov"
        fi
    fi
}

apply_rules() { # $1=时间戳；设置 AR_STATUS/AR_BACKUP/APPLY_ERR
    AR_STATUS='' AR_BACKUP='' APPLY_ERR=''
    if [ "$RULES_ACTION" = 'skip' ]; then AR_STATUS='跳过'; return 0; fi
    target=$HOST_RULES
    if [ -e "$target" ] && [ "$(wc -c < "$target" | tr -d ' ')" -gt 0 ]; then
        AR_BACKUP=$(do_backup "$HOST_ROOT/_backup/$(backup_name "$(basename -- "$target")" "$1")" "$target") || {
            APPLY_ERR="备份失败: $target"; return 1
        }
    fi
    if is_crlf "$WORK/old_rules"; then NLFLAG=1; else NLFLAG=0; fi
    case $RULES_ACTION in
        create)
            block_nl "$WORK/source_block" "$WORK/.out" 0
            atomic_install "$WORK/.out" "$target" || { APPLY_ERR="写入失败: $target"; return 1; }
            AR_STATUS='新建'
            ;;
        rewrite)
            if has_bom "$target"; then tail -c +4 "$target" > "$WORK/.raw"; else cat "$target" > "$WORK/.raw"; fi
            atomic_install "$WORK/.raw" "$target" || { APPLY_ERR="写入失败: $target"; return 1; }
            AR_STATUS='剥离 BOM 原样重写'
            ;;
        replace_block)
            block_nl "$WORK/source_block" "$WORK/.blk" "$NLFLAG"
            {
                head -n $((RULES_BL - 1)) "$WORK/old_rules"
                cat "$WORK/.blk"
                tail -n +$((RULES_EL + 1)) "$WORK/old_rules"
            } > "$WORK/.out"
            atomic_install "$WORK/.out" "$target" || { APPLY_ERR="写入失败: $target"; return 1; }
            AR_STATUS='替换受管区块'
            ;;
        append)
            block_nl "$WORK/source_block" "$WORK/.blk" "$NLFLAG"
            {
                cat "$WORK/old_rules"
                if ! ends_with_newline "$WORK/old_rules"; then
                    if [ "$NLFLAG" = "1" ]; then printf '\r\n'; else printf '\n'; fi
                fi
                if [ "$NLFLAG" = "1" ]; then printf '\r\n'; else printf '\n'; fi
                cat "$WORK/.blk"
            } > "$WORK/.out"
            atomic_install "$WORK/.out" "$target" || { APPLY_ERR="写入失败: $target"; return 1; }
            AR_STATUS='追加受管区块'
            ;;
        replace_file)
            block_nl "$WORK/source_block" "$WORK/.out" "$NLFLAG"
            atomic_install "$WORK/.out" "$target" || { APPLY_ERR="写入失败: $target"; return 1; }
            AR_STATUS='整文件替换'
            ;;
        *)
            APPLY_ERR="未知规则动作: $RULES_ACTION"; return 1
            ;;
    esac
    return 0
}

apply_skill() { # $1=skill 名 $2=时间戳；设置 AS_STATUS/AS_BACKUP/APPLY_ERR
    AS_STATUS='' AS_BACKUP='' APPLY_ERR=''
    if [ "$SK_ACTION" = 'skip' ]; then AS_STATUS='跳过'; return 0; fi
    target=$HOST_SKILLS/$1/SKILL.md
    mkdir -p -- "$(dirname -- "$target")" || { APPLY_ERR="创建目录失败: $target"; return 1; }
    if [ -e "$target" ]; then
        AS_BACKUP=$(do_backup "$HOST_ROOT/_backup/skills/$1/$(backup_name 'SKILL.md' "$2")" "$target") || {
            APPLY_ERR="备份失败: $target"; return 1
        }
    fi
    tr -d '\r' < "$WORK/src_$1" > "$WORK/.out"
    atomic_install "$WORK/.out" "$target" || { APPLY_ERR="写入失败: $target"; return 1; }
    if [ "$SK_ACTION" = 'create' ]; then AS_STATUS='新建'; else AS_STATUS='覆盖'; fi
    return 0
}

verify_host() {
    ok=0
    printf '\n=== 校验 %s (%s) ===\n' "$HOST_LABEL" "$HOST_KEY"
    printf '规则文件: %s\n' "$HOST_RULES"
    if [ ! -f "$HOST_RULES" ]; then
        printf '  FAIL: 规则文件不存在\n'
        return 1
    fi
    decode "$HOST_RULES" "$WORK/v_rules"
    bc=$(marker_count "$BEGIN_MARK" "$WORK/v_rules")
    ec=$(marker_count "$END_MARK" "$WORK/v_rules")
    bl=$(line_no "$BEGIN_MARK" "$WORK/v_rules")
    el=$(line_no "$END_MARK" "$WORK/v_rules")
    has_block=0
    if [ "$bc" != "1" ] || [ "$ec" != "1" ] || [ "$el" -lt "$bl" ]; then
        printf '  FAIL: 标记异常 BEGIN=%s END=%s\n' "$bc" "$ec"
        ok=1
    else
        extract_block "$WORK/v_rules" > "$WORK/v_block"
        has_block=1
        if same_normalized "$WORK/v_block" "$WORK/source_block"; then m='OK'; else m='FAIL'; ok=1; fi
        lines=$(awk 'END { print NR }' "$WORK/v_block")
        printf '  受管区块: %s (%s 行)\n' "$m" "$lines"
    fi
    if ! grep -q -F '# 全局核心铁律' "$WORK/v_rules"; then
        printf '  FAIL: 缺少标题“全局核心铁律”\n'
        ok=1
    fi
    if [ "$has_block" = "1" ]; then
        if awk '{ if ($0 ~ /^[0-9]+[.] [][*][*]/) { match($0, /^[0-9]+/); seen[substr($0, RSTART, RLENGTH) + 0] = 1 } } END { c = 0; for (k in seen) { c++; if (k + 0 < 1 || k + 0 > 10) bad = 1 } if (c != 10) bad = 1; exit (bad ? 1 : 0) }' "$WORK/v_block"; then
            printf '  铁律条数: OK (1-10)\n'
        else
            printf '  FAIL: 铁律编号不是 1-10\n'
            ok=1
        fi
    fi
    if has_bom "$HOST_RULES"; then
        printf '  BOM: FAIL (存在 BOM)\n'; ok=1
    else
        printf '  BOM: OK (无)\n'
    fi
    if is_crlf "$WORK/v_rules"; then
        printf '  换行: CRLF（沿用原文件）\n'
    else
        printf '  换行: LF\n'
    fi
    for name in $SKILL_NAMES; do
        target=$HOST_SKILLS/$name/SKILL.md
        printf 'Skill %s: %s\n' "$name" "$target"
        if [ ! -f "$target" ]; then
            printf '  FAIL: 文件不存在\n'; ok=1; continue
        fi
        decode "$target" "$WORK/v_skill"
        if same_normalized "$WORK/v_skill" "$WORK/src_$name"; then m='OK'; else m='FAIL'; ok=1; fi
        lines=$(awk 'END { print NR }' "$WORK/v_skill")
        printf '  %s (%s 行)\n' "$m" "$lines"
        first=$(sed -n '1p' "$WORK/v_skill")
        case $first in
            ---*)
                cend=$(awk 'NR > 1 && index($0, "---") == 1 { print NR; exit }' "$WORK/v_skill")
                fm=''
                if [ -n "$cend" ] && [ "$((cend - 1))" -ge 2 ]; then
                    fm=$(sed -n "2,$((cend - 1))p" "$WORK/v_skill")
                fi
                nm=$(printf '%s\n' "$fm" | sed -n 's/^name:[[:space:]]*//p' | head -n 1 | tr -d '[:space:]"' | tr -d "'")
                if [ "$nm" != "$name" ]; then
                    printf '  FAIL: frontmatter 的 name 缺失或与目录名不一致\n'; ok=1
                fi
                dv=$(printf '%s\n' "$fm" | sed -n 's/^description:[[:space:]]*//p' | head -n 1 | tr -d '[:space:]"' | tr -d "'")
                case $dv in
                    ''|'>'|'|'|'>-'|'|-') printf '  FAIL: frontmatter 缺少单行 description\n'; ok=1 ;;
                esac
                ;;
            *)
                printf '  FAIL: 缺少 YAML frontmatter\n'; ok=1
                ;;
        esac
        if has_bom "$target"; then printf '  FAIL: 存在 BOM\n'; ok=1; fi
        if is_crlf "$target"; then printf '  FAIL: 存在 CRLF\n'; ok=1; fi
    done
    return $ok
}

resolve_targets() {
    case $1 in
        auto)
            signal=''
            if [ -n "$CLAUDECODE" ] || [ -n "$CLAUDE_CODE_ENTRYPOINT" ]; then
                signal=claude
            elif [ -n "$CODEX_THREAD_ID" ]; then
                signal=codex
            fi
            if [ -n "$signal" ]; then
                printf '检测依据: 环境变量 -> %s\n' "$signal"
                HOST_KEYS=$signal
                return 0
            fi
            existing=''
            for k in claude codex; do
                [ -e "$HOME_BASE/.$k" ] && existing="$existing $k"
            done
            case $existing in
                ' claude') printf '检测依据: 仅存在 ~/.claude -> claude\n'; HOST_KEYS=claude ;;
                ' codex') printf '检测依据: 仅存在 ~/.codex -> codex\n'; HOST_KEYS=codex ;;
                ' claude codex') die '同时检测到 ~/.claude 与 ~/.codex，无法唯一确定宿主。\n请用 --target claude、--target codex 或 --target both 明确指定。' ;;
                *) die '未检测到 ~/.claude 或 ~/.codex，请用 --target 明确指定（可先创建对应目录）。' ;;
            esac
            ;;
        both) HOST_KEYS='claude codex' ;;
        claude|codex|agents) HOST_KEYS=$1 ;;
        *) die "未知 --target: $1" ;;
    esac
    return 0
}

fail_report() { # $1=错误信息
    printf '\n失败: %s\n' "$1"
    if [ -s "$W_WRITTEN" ]; then printf '已写入:\n'; cat "$W_WRITTEN"; else printf '已写入: 无\n'; fi
    if [ -s "$W_BACKUPS" ]; then
        printf '已备份（把备份复制回箭头右侧原路径即可回滚，脚本不自动回滚）:\n'
        cat "$W_BACKUPS"
    else
        printf '已备份: 无\n'
    fi
    printf '未处理: 其余\n'
}

main() {
    target=auto
    mode=append
    home_arg=''
    action=''
    while [ $# -gt 0 ]; do
        case $1 in
            --version) printf 'agent-config %s (sh)\n' "$VERSION"; exit 0 ;;
            --target)
                [ $# -ge 2 ] || die '缺少 --target 的值'
                target=$2; shift 2 ;;
            --mode)
                [ $# -ge 2 ] || die '缺少 --mode 的值'
                mode=$2; shift 2 ;;
            --home)
                [ $# -ge 2 ] || die '缺少 --home 的值'
                home_arg=$2; shift 2 ;;
            --dry-run|--apply|--verify)
                [ -z "$action" ] || die '--dry-run/--apply/--verify 只能选一个'
                action=${1#--}; shift ;;
            *) die "未知参数: $1" ;;
        esac
    done
    case $target in
        auto|claude|codex|agents|both) ;;
        *) die "未知 --target: $target" ;;
    esac
    case $mode in
        append|replace|abort) ;;
        *) die "未知 --mode: $mode" ;;
    esac
    [ -n "$action" ] || action=dry-run
    if [ -n "$home_arg" ]; then
        case $home_arg in
            '~') HOME_BASE=$REAL_HOME ;;
            '~/'*) HOME_BASE=$REAL_HOME/${home_arg#~/} ;;
            *) HOME_BASE=$home_arg ;;
        esac
    else
        HOME_BASE=$REAL_HOME
    fi
    load_source_rules
    resolve_targets "$target"
    # 第一遍：全部规划；任何规划错误在此停止（未输出、未写入）
    for k in $HOST_KEYS; do
        set_host "$k"
        plan_rules "$mode"
        for name in $SKILL_NAMES; do plan_skill "$name"; done
    done
    if [ "$action" = 'verify' ]; then
        all_ok=0
        for k in $HOST_KEYS; do
            set_host "$k"
            verify_host || all_ok=1
        done
        if [ "$all_ok" = "0" ]; then printf '\n结论: 全部通过\n'; return 0; fi
        printf '\n结论: 存在失败项\n'
        return 1
    fi
    # 第二遍：打印计划
    for k in $HOST_KEYS; do
        set_host "$k"
        plan_rules "$mode"
        print_plan
    done
    if [ "$action" != 'apply' ]; then
        printf '\n以上为 dry-run（未写入任何配置文件）。确认后用 --apply 执行。\n'
        return 0
    fi
    t=$(ts_now)
    for k in $HOST_KEYS; do
        set_host "$k"
        plan_rules "$mode"
        if ! apply_rules "$t"; then fail_report "$APPLY_ERR"; return 1; fi
        if [ "$AR_STATUS" = '跳过' ]; then
            printf '%s 规则: 已最新\n' "$k" >> "$W_SKIPPED"
        else
            printf '%s 规则: %s\n' "$k" "$AR_STATUS" >> "$W_WRITTEN"
        fi
        [ -n "$AR_BACKUP" ] && printf '%s -> %s\n' "$AR_BACKUP" "$HOST_RULES" >> "$W_BACKUPS"
        for name in $SKILL_NAMES; do
            plan_skill "$name"
            if ! apply_skill "$name" "$t"; then fail_report "$APPLY_ERR"; return 1; fi
            if [ "$AS_STATUS" = '跳过' ]; then
                printf '%s Skill %s: 已最新\n' "$k" "$name" >> "$W_SKIPPED"
            else
                printf '%s Skill %s: %s\n' "$k" "$name" "$AS_STATUS" >> "$W_WRITTEN"
            fi
            [ -n "$AS_BACKUP" ] && printf '%s -> %s\n' "$AS_BACKUP" "$HOST_SKILLS/$name/SKILL.md" >> "$W_BACKUPS"
        done
    done
    printf '\n=== 执行结果 ===\n'
    [ -s "$W_WRITTEN" ] && { printf '写入:\n'; cat "$W_WRITTEN"; }
    [ -s "$W_BACKUPS" ] && { printf '备份:\n'; cat "$W_BACKUPS"; }
    [ -s "$W_SKIPPED" ] && { printf '跳过:\n'; cat "$W_SKIPPED"; }
    printf '\n下一步: sh install.sh --verify --target %s\n' "$target"
    return 0
}

main "$@"
