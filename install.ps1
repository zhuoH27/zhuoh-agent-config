# agent-config 安装器（Windows PowerShell 5.1+ / pwsh 7 兼容版）。
# 为兼容 Windows PowerShell 5.1 的编码探测，本文件以 UTF-8（带 BOM）、CRLF 保存（见 .gitattributes）。
# 安全边界：无网络访问；无子进程；无 eval；只读写宿主规则文件、skills/*/SKILL.md 与 _backup/；写入前先备份，临时文件+原子替换。
# 环境变量 AGENT_CONFIG_TS 仅供测试固定备份时间戳。
# 用法：powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 [--dry-run|--apply|--verify]
#       [--target auto|claude|codex|agents|both] [--mode append|replace|abort] [--home 目录]

$VERSION = '2.1.1'
$BEGIN_MARK = '<!-- BEGIN: global-iron-rules -->'
$END_MARK = '<!-- END: global-iron-rules -->'
$SKILL_NAMES = @('zhuoh-code-standards', 'zhuoh-ppt-maker', 'zhuoh-paper-writing', 'zhuoh-idea-evaluation')
$TS_HINT = 'YYYYMMDD_HHMMSS'
$KNOWN_OVERLAPS = @{
    'coding-standards' = 'zhuoh-code-standards'
    'academic-pptx' = 'zhuoh-ppt-maker'
    'nature-paper2ppt' = 'zhuoh-ppt-maker'
    'scientific-figure-making' = 'zhuoh-ppt-maker'
    'anti-defensive-writing' = 'zhuoh-paper-writing'
    'code-standards' = 'zhuoh-code-standards'
    'ppt-maker' = 'zhuoh-ppt-maker'
    'paper-writing' = 'zhuoh-paper-writing'
    'idea-evaluation' = 'zhuoh-idea-evaluation'
}
$REPO = $PSScriptRoot
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); [Console]::ErrorEncoding = [Text.UTF8Encoding]::new($false) } catch {}

function Out-Line([string]$s) { [Console]::Out.WriteLine($s) }
function Err-Line([string]$s) { [Console]::Error.WriteLine($s) }
function Die([string]$s) { Err-Line $s; exit 1 }

function Test-Bom([string]$path) {
    try {
        $b = [IO.File]::ReadAllBytes($path)
        return ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)
    } catch { return $false }
}

# 读取：剥离 BOM 并按严格 UTF-8 解码；非 UTF-8 文件以可读错误停止
function Read-TextStrict([string]$path) {
    try {
        $bytes = [IO.File]::ReadAllBytes($path)
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
            if ($bytes.Length -eq 3) { return '' }
            $bytes = $bytes[3..($bytes.Length - 1)]
        }
        return [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
    } catch {
        Die ("无法按 UTF-8 解码 {0}。若文件是 GBK/UTF-16 等编码，请先转成 UTF-8 再运行；脚本不猜测编码。" -f $path)
    }
}

function Get-Newline([string]$text) {
    if ($text -and $text.Contains("`r")) { return "`r`n" }
    return "`n"
}

function Normalize([string]$text) {
    return (($text -replace "`r`n", "`n") -replace "`r", "`n")
}

function To-Nl([string]$text, [string]$nl) {
    $n = Normalize $text
    if ($nl -eq "`r`n") { return ($n -replace "`n", "`r`n") }
    return $n
}

function Get-Block([string]$text) {
    $i = $text.IndexOf($BEGIN_MARK)
    $j = $text.IndexOf($END_MARK)
    if ($i -lt 0 -or $j -lt 0 -or $j -lt $i) { throw '受管标记不完整' }
    return $text.Substring($i, $j + $END_MARK.Length - $i).Trim([char[]](@([char]13, [char]10)))
}

function Test-MarkerLayout([string]$text) {
    $lines = (Normalize $text) -split "`n"
    $bl = @($lines | Where-Object { $_ -eq $BEGIN_MARK }).Count
    $el = @($lines | Where-Object { $_ -eq $END_MARK }).Count
    return ($bl -eq 1 -and $el -eq 1)
}

function Get-SourceBlock {
    if ($script:SourceBlock) { return $script:SourceBlock }
    $p = Join-Path $REPO 'AGENTS.md'
    if (-not (Test-Path -LiteralPath $p)) { Die ("缺少源规则文件: {0}" -f $p) }
    $text = Read-TextStrict $p
    $bc = [regex]::Matches($text, [regex]::Escape($BEGIN_MARK)).Count
    $ec = [regex]::Matches($text, [regex]::Escape($END_MARK)).Count
    if ($bc -ne 1 -or $ec -ne 1 -or -not (Test-MarkerLayout $text)) { Die '源 AGENTS.md 的受管标记不成对或未独占一行' }
    $i = $text.IndexOf($BEGIN_MARK)
    $j = $text.IndexOf($END_MARK)
    if ($j -lt $i) { Die '源 AGENTS.md 的 END 在 BEGIN 之前' }
    $script:SourceBlock = Get-Block $text
    return $script:SourceBlock
}

function Get-SkillSource([string]$name) {
    $key = 'skill:' + $name
    if (-not $script:SkillSources) { $script:SkillSources = @{} }
    if ($script:SkillSources.ContainsKey($key)) { return $script:SkillSources[$key] }
    $p = Join-Path $REPO ("skills/" + $name + "/SKILL.md")
    if (-not (Test-Path -LiteralPath $p)) { Die ("缺少源 Skill: {0}" -f $p) }
    $script:SkillSources[$key] = (Normalize (Read-TextStrict $p))
    return $script:SkillSources[$key]
}

function New-HostCtx([string]$key, [string]$homeBase) {
    $root = Join-Path $homeBase ('.' + $key)
    $labels = @{ 'claude' = 'Claude Code'; 'codex' = 'Codex CLI'; 'agents' = '~/.agents 约定' }
    $rulesName = 'AGENTS.md'
    if ($key -eq 'claude') { $rulesName = 'CLAUDE.md' }
    return [pscustomobject]@{ Key = $key; Label = $labels[$key]; Root = $root; Rules = (Join-Path $root $rulesName); Skills = (Join-Path $root 'skills') }
}

function Get-BackupName([string]$name, [string]$ts) {
    $dot = $name.LastIndexOf('.')
    if ($dot -ge 0) {
        return ($name.Substring(0, $dot) + '_' + $ts + '.' + $name.Substring($dot + 1) + '.bak')
    }
    return ($name + '_' + $ts + '.bak')
}

function Get-UniquePath([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $path }
    $dir = Split-Path -Parent $path
    $leaf = Split-Path -Leaf $path
    $base = $leaf
    if ($leaf.EndsWith('.bak')) { $base = $leaf.Substring(0, $leaf.Length - 4) }
    $stem = $base
    $ext = ''
    $dot = $base.LastIndexOf('.')
    if ($dot -ge 0) {
        $stem = $base.Substring(0, $dot)
        $ext = $base.Substring($dot + 1)
    }
    $n = 2
    while ($true) {
        $cand = if ($ext) { Join-Path $dir ("{0}_{1}.{2}.bak" -f $stem, $n, $ext) } else { Join-Path $dir ("{0}_{1}.bak" -f $stem, $n) }
        if (-not (Test-Path -LiteralPath $cand)) { return $cand }
        $n++
    }
}

function Backup-File([string]$desired, [string]$src) {
    $dir = Split-Path -Parent $desired
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $dest = Get-UniquePath $desired
    Copy-Item -LiteralPath $src -Destination $dest -Force
    return $dest
}

function Write-AtomicText([string]$path, [string]$text) {
    Write-AtomicBytes $path ([Text.UTF8Encoding]::new($false).GetBytes($text))
}

function Write-AtomicBytes([string]$path, [byte[]]$bytes) {
    $dir = Split-Path -Parent $path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = Join-Path $dir ('.' + (Split-Path -Leaf $path) + '.tmp.' + $PID)
    [IO.File]::WriteAllBytes($tmp, $bytes)
    if (Test-Path -LiteralPath $path) {
        try { [IO.File]::Replace($tmp, $path, $null) } catch { Move-Item -LiteralPath $tmp -Destination $path -Force }
    } else {
        Move-Item -LiteralPath $tmp -Destination $path -Force
    }
}

function Plan-Rules($ctx, [string]$mode) {
    $target = $ctx.Rules
    if (Test-Path -LiteralPath $target) {
        $li = Get-Item -LiteralPath $target -Force
        if ($li.LinkType) { Die ("规则文件是符号链接，拒绝写入: {0}" -f $target) }
    }
    if (-not (Test-Path -LiteralPath $target)) {
        return @{ Action = 'create'; Reason = '规则文件不存在，将新建'; Backup = ''; Target = $target }
    }
    $text = Read-TextStrict $target
    $size = (Get-Item -LiteralPath $target).Length
    $bc = [regex]::Matches($text, [regex]::Escape($BEGIN_MARK)).Count
    $ec = [regex]::Matches($text, [regex]::Escape($END_MARK)).Count
    $i = $text.IndexOf($BEGIN_MARK)
    $j = $text.IndexOf($END_MARK)
    if ($bc -eq 1 -and $ec -eq 1 -and $j -ge $i -and (Test-MarkerLayout $text)) {
        $block = Get-Block $text
        $src = Get-SourceBlock
        if ((Normalize $block) -eq (Normalize $src)) {
            if (Test-Bom $target) {
                return @{ Action = 'rewrite'; Reason = '受管区块已是最新，但文件带 BOM；将备份后原样重写（仅剥离 BOM）'; Backup = (Join-Path (Join-Path $ctx.Root '_backup') (Get-BackupName (Split-Path -Leaf $target) $TS_HINT)); Target = $target }
            }
            return @{ Action = 'skip'; Reason = '受管区块已是最新'; Backup = ''; Target = $target }
        }
        return @{ Action = 'replace_block'; Reason = '将替换受管区块'; Backup = (Join-Path (Join-Path $ctx.Root '_backup') (Get-BackupName (Split-Path -Leaf $target) $TS_HINT)); Target = $target }
    }
    if ($bc -gt 0 -or $ec -gt 0) {
        Die ("标记异常: {0} (BEGIN={1}, END={2})；标记须各出现一次且独占一行，请先手动修复，脚本不自动修" -f $target, $bc, $ec)
    }
    if ($size -eq 0) {
        return @{ Action = 'create'; Reason = '规则文件为空，将写入'; Backup = ''; Target = $target }
    }
    if ([string]::IsNullOrWhiteSpace($text)) {
        return @{ Action = 'replace_file'; Reason = '规则文件仅含空白，备份后写入'; Backup = (Join-Path (Join-Path $ctx.Root '_backup') (Get-BackupName (Split-Path -Leaf $target) $TS_HINT)); Target = $target }
    }
    if ($mode -eq 'abort') {
        Die ("{0} 已有内容但没有受管标记；按 --mode abort 停止" -f $target)
    }
    if ($mode -eq 'replace') {
        return @{ Action = 'replace_file'; Reason = '按 --mode replace 整文件替换'; Backup = (Join-Path (Join-Path $ctx.Root '_backup') (Get-BackupName (Split-Path -Leaf $target) $TS_HINT)); Target = $target }
    }
    $reason = '已有内容无标记，将追加受管区块（保留原内容）'
    if ($text.Contains('全局核心铁律') -or $text.Contains('不可逆操作确认')) {
        $reason = $reason + '；[警告] 疑似已有旧版未受管铁律，直接追加会重复或冲突，请人工合并，或经用户确认后改用 --mode replace'
    }
    return @{ Action = 'append'; Reason = $reason; Backup = (Join-Path (Join-Path $ctx.Root '_backup') (Get-BackupName (Split-Path -Leaf $target) $TS_HINT)); Target = $target }
}

function Plan-Skill($ctx, [string]$name) {
    $target = Join-Path (Join-Path $ctx.Skills $name) 'SKILL.md'
    if (Test-Path -LiteralPath $target) {
        $li = Get-Item -LiteralPath $target -Force
        if ($li.LinkType) { Die ("Skill 文件是符号链接，拒绝写入: {0}" -f $target) }
    }
    $others = @()
    $skillDir = Split-Path -Parent $target
    if (Test-Path -LiteralPath $skillDir) {
        $others = @(Get-ChildItem -LiteralPath $skillDir -File | Where-Object { $_.Name -ne 'SKILL.md' } | ForEach-Object { $_.Name })
    }
    if (-not (Test-Path -LiteralPath $target)) {
        return @{ Name = $name; Action = 'create'; Reason = '将新建'; Others = $others; Backup = ''; Target = $target }
    }
    $old = Normalize (Read-TextStrict $target)
    $new = Get-SkillSource $name
    if ($old -eq $new) {
        return @{ Name = $name; Action = 'skip'; Reason = '已是最新'; Others = $others; Backup = ''; Target = $target }
    }
    return @{ Name = $name; Action = 'replace'; Reason = '将备份后覆盖 SKILL.md'; Others = $others; Backup = (Join-Path (Join-Path (Join-Path $ctx.Root '_backup') 'skills') (Join-Path $name (Get-BackupName 'SKILL.md' $TS_HINT))); Target = $target }
}

function Get-BlockDiff([string]$oldBlock, [string]$newBlock) {
    $o = (Normalize $oldBlock) -split "`n"
    $n = (Normalize $newBlock) -split "`n"
    $max = [Math]::Max($o.Count, $n.Count)
    $count = 0
    $examples = @()
    for ($ix = 0; $ix -lt $max; $ix++) {
        $a = $null
        $b = $null
        if ($ix -lt $o.Count) { $a = $o[$ix] }
        if ($ix -lt $n.Count) { $b = $n[$ix] }
        if ($a -ne $b) {
            $count++
            if ($examples.Count -lt 6) {
                $examples += ('-' + $a)
                $examples += ('+' + $b)
            }
        }
    }
    return @{ Count = $count; Examples = $examples }
}

function Show-Plan($ctx, $rp, $sps) {
    Out-Line ("`n宿主: {0} ({1})" -f $ctx.Label, $ctx.Key)
    Out-Line ("  根目录: {0}" -f $ctx.Root)
    Out-Line ("  规则文件: {0}" -f $ctx.Rules)
    Out-Line ("  Skills 目录: {0}" -f $ctx.Skills)
    Out-Line ("  规则处理: {0} - {1}" -f $rp.Action, $rp.Reason)
    if ($rp.Backup) { Out-Line ("    将备份到: {0}" -f $rp.Backup) }
    if ($rp.Action -eq 'replace_block') {
        $oldBlock = Get-Block (Read-TextStrict $rp.Target)
        $diff = Get-BlockDiff $oldBlock (Get-SourceBlock)
        Out-Line ("    区块差异（共约 {0} 行不同）:" -f $diff.Count)
        foreach ($ex in $diff.Examples) { Out-Line ('    ' + $ex) }
    }
    foreach ($sp in $sps) {
        Out-Line ("  Skill {0}: {1} - {2}" -f $sp.Name, $sp.Action, $sp.Reason)
        if ($sp.Backup) { Out-Line ("    将备份到: {0}" -f $sp.Backup) }
        if ($sp.Others.Count -gt 0) { Out-Line ("    目录内其他文件（不会改动）: {0}" -f ($sp.Others -join ', ')) }
    }
    if (Test-Path -LiteralPath $ctx.Skills) {
        $existing = @(Get-ChildItem -LiteralPath $ctx.Skills -Directory | Where-Object { $SKILL_NAMES -notcontains $_.Name } | ForEach-Object { $_.Name })
        if ($existing.Count -gt 0) {
            Out-Line ("  现有其他 Skill（不会改动）: {0}" -f ($existing -join ', '))
            $ov = @()
            foreach ($e in $existing) {
                if ($KNOWN_OVERLAPS.ContainsKey($e)) { $ov += ("{0} ≈ {1}" -f $e, $KNOWN_OVERLAPS[$e]) }
            }
            if ($ov.Count -gt 0) { Out-Line ("  可能功能重叠（仅提醒，不删除）: {0}" -f ($ov -join ', ')) }
        }
    }
}

function Apply-Rules($ctx, $rp, [string]$ts) {
    if ($rp.Action -eq 'skip') { return @{ Status = '跳过'; Backup = $null } }
    $target = $rp.Target
    $backup = $null
    if ((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target).Length -gt 0)) {
        $backup = Backup-File (Join-Path (Join-Path $ctx.Root '_backup') (Get-BackupName (Split-Path -Leaf $target) $ts)) $target
    }
    $source = Get-SourceBlock
    switch ($rp.Action) {
        'create' {
            Write-AtomicText $target ((Normalize $source) + "`n")
            return @{ Status = '新建'; Backup = $backup }
        }
        'rewrite' {
            $raw = [IO.File]::ReadAllBytes($target)
            if ($raw.Length -ge 3 -and $raw[0] -eq 0xEF -and $raw[1] -eq 0xBB -and $raw[2] -eq 0xBF) {
                if ($raw.Length -eq 3) { $raw = @() } else { $raw = $raw[3..($raw.Length - 1)] }
            }
            Write-AtomicBytes $target $raw
            return @{ Status = '剥离 BOM 原样重写'; Backup = $backup }
        }
        'replace_block' {
            $old = Read-TextStrict $target
            $nl = Get-Newline $old
            $i = $old.IndexOf($BEGIN_MARK)
            $j = $old.IndexOf($END_MARK)
            if ($i -lt 0 -or $j -lt 0) { Die ("受管标记在写入前消失: {0}" -f $target) }
            $new = $old.Substring(0, $i) + (To-Nl $source $nl) + $old.Substring($j + $END_MARK.Length)
            Write-AtomicText $target $new
            return @{ Status = '替换受管区块'; Backup = $backup }
        }
        'append' {
            $old = Read-TextStrict $target
            $nl = Get-Newline $old
            $t = $old
            if (-not $old.EndsWith("`n")) { $t = $old + $nl }
            $new = $t + $nl + (To-Nl $source $nl) + $nl
            Write-AtomicText $target $new
            return @{ Status = '追加受管区块'; Backup = $backup }
        }
        'replace_file' {
            $old = Read-TextStrict $target
            $nl = Get-Newline $old
            Write-AtomicText $target ((To-Nl $source $nl) + $nl)
            return @{ Status = '整文件替换'; Backup = $backup }
        }
        default {
            Die ("未知规则动作: {0}" -f $rp.Action)
        }
    }
}

function Apply-Skill($ctx, $sp, [string]$ts) {
    if ($sp.Action -eq 'skip') { return @{ Status = '跳过'; Backup = $null } }
    $target = $sp.Target
    $backup = $null
    if (Test-Path -LiteralPath $target) {
        $backup = Backup-File (Join-Path (Join-Path (Join-Path $ctx.Root '_backup') 'skills') (Join-Path $sp.Name (Get-BackupName 'SKILL.md' $ts))) $target
    }
    Write-AtomicText $target (Get-SkillSource $sp.Name)
    if ($sp.Action -eq 'create') { return @{ Status = '新建'; Backup = $backup } }
    return @{ Status = '覆盖'; Backup = $backup }
}

function Verify-Host($ctx) {
    $ok = $true
    Out-Line ("`n=== 校验 {0} ({1}) ===" -f $ctx.Label, $ctx.Key)
    Out-Line ("规则文件: {0}" -f $ctx.Rules)
    if (-not (Test-Path -LiteralPath $ctx.Rules)) {
        Out-Line '  FAIL: 规则文件不存在'
        return $false
    }
    $text = Read-TextStrict $ctx.Rules
    $bc = [regex]::Matches($text, [regex]::Escape($BEGIN_MARK)).Count
    $ec = [regex]::Matches($text, [regex]::Escape($END_MARK)).Count
    $i = $text.IndexOf($BEGIN_MARK)
    $j = $text.IndexOf($END_MARK)
    $block = ''
    if ($bc -ne 1 -or $ec -ne 1 -or $j -lt $i -or -not (Test-MarkerLayout $text)) {
        Out-Line ("  FAIL: 标记异常 BEGIN={0} END={1}" -f $bc, $ec)
        $ok = $false
    } else {
        $block = Get-Block $text
        $src = Get-SourceBlock
        $m = 'FAIL'
        if ((Normalize $block) -eq (Normalize $src)) { $m = 'OK' } else { $ok = $false }
        $lines = ((Normalize $block) -split "`n").Count
        Out-Line ("  受管区块: {0} ({1} 行)" -f $m, $lines)
    }
    if (-not $text.Contains('# 全局核心铁律')) {
        Out-Line '  FAIL: 缺少标题“全局核心铁律”'
        $ok = $false
    }
    if ($block) {
        $nums = @([regex]::Matches($block, '(?m)^(\d+)\. \*\*') | ForEach-Object { [int]$_.Groups[1].Value } | Sort-Object -Unique)
        $expected = @(1..10)
        $bad = ($nums.Count -ne 10)
        if (-not $bad) {
            for ($ix = 0; $ix -lt 10; $ix++) { if ($nums[$ix] -ne $expected[$ix]) { $bad = $true; break } }
        }
        if ($bad) {
            Out-Line ('  FAIL: 铁律编号不是 1-10')
            $ok = $false
        } else {
            Out-Line '  铁律条数: OK (1-10)'
        }
    }
    if (Test-Bom $ctx.Rules) { Out-Line '  BOM: FAIL (存在 BOM)'; $ok = $false } else { Out-Line '  BOM: OK (无)' }
    $nl = Get-Newline $text
    if ($nl -eq "`r`n") { Out-Line '  换行: CRLF（沿用原文件）' } else { Out-Line '  换行: LF' }
    foreach ($name in $SKILL_NAMES) {
        $target = Join-Path (Join-Path $ctx.Skills $name) 'SKILL.md'
        Out-Line ("Skill {0}: {1}" -f $name, $target)
        if (-not (Test-Path -LiteralPath $target)) {
            Out-Line '  FAIL: 文件不存在'
            $ok = $false
            continue
        }
        $skillText = Read-TextStrict $target
        $m = 'FAIL'
        if ((Normalize $skillText) -eq (Get-SkillSource $name)) { $m = 'OK' } else { $ok = $false }
        $lines = ((Normalize $skillText) -split "`n").Count
        Out-Line ("  {0} ({1} 行)" -f $m, $lines)
        if (-not $skillText.StartsWith('---')) {
            Out-Line '  FAIL: 缺少 YAML frontmatter'
            $ok = $false
        } else {
            $nText = Normalize $skillText
            $fmEnd = $nText.IndexOf("`n---", 3)
            $front = ''
            if ($fmEnd -ge 0) { $front = $nText.Substring(0, $fmEnd) }
            $mName = [regex]::Match($front, '(?m)^name:[ \t]*(\S+)[ \t]*$')
            if (-not $mName.Success -or $mName.Groups[1].Value.Trim([char[]]@(39, 34)) -ne $name) {
                Out-Line '  FAIL: frontmatter 的 name 缺失或与目录名不一致'
                $ok = $false
            }
            $mDesc = [regex]::Match($front, '(?m)^description:[ \t]*(.+)$')
            $dv = ''
            if ($mDesc.Success) { $dv = $mDesc.Groups[1].Value.Trim().Trim([char[]]@(39, 34)) }
            if ($dv -eq '' -or $dv -eq '>' -or $dv -eq '|' -or $dv -eq '>-' -or $dv -eq '|-') {
                Out-Line '  FAIL: frontmatter 缺少单行 description'
                $ok = $false
            }
        }
        if (Test-Bom $target) { Out-Line '  FAIL: 存在 BOM'; $ok = $false }
        if ($skillText.Contains("`r")) { Out-Line '  FAIL: 存在 CRLF'; $ok = $false }
    }
    return $ok
}

function Resolve-Targets([string]$target, [string]$homeBase) {
    if ($target -eq 'auto') {
        $signal = ''
        if ([Environment]::GetEnvironmentVariable('CLAUDECODE') -or [Environment]::GetEnvironmentVariable('CLAUDE_CODE_ENTRYPOINT')) {
            $signal = 'claude'
        } elseif ([Environment]::GetEnvironmentVariable('CODEX_THREAD_ID')) {
            $signal = 'codex'
        }
        if ($signal) {
            Out-Line ("检测依据: 环境变量 -> {0}" -f $signal)
            return @(New-HostCtx $signal $homeBase)
        }
        $existing = @()
        foreach ($k in @('claude', 'codex')) {
            if (Test-Path -LiteralPath (Join-Path $homeBase ('.' + $k))) { $existing += $k }
        }
        if ($existing.Count -eq 1) {
            Out-Line ("检测依据: 仅存在 ~/.{0} -> {1}" -f $existing[0], $existing[0])
            return @(New-HostCtx $existing[0] $homeBase)
        }
        if ($existing.Count -eq 2) {
            Die "同时检测到 ~/.claude 与 ~/.codex，无法唯一确定宿主。`n请用 --target claude、--target codex 或 --target both 明确指定。"
        }
        Die '未检测到 ~/.claude 或 ~/.codex，请用 --target 明确指定（可先创建对应目录）。'
    }
    if ($target -eq 'both') {
        return @((New-HostCtx 'claude' $homeBase), (New-HostCtx 'codex' $homeBase))
    }
    return @(New-HostCtx $target $homeBase)
}

function Fail-Report([string]$msg, $written, $backups) {
    Out-Line ("`n失败: {0}" -f $msg)
    if ($written.Count -gt 0) { Out-Line '已写入:'; foreach ($w in $written) { Out-Line ('  ' + $w) } }
    else { Out-Line '已写入: 无' }
    if ($backups.Count -gt 0) {
        Out-Line '已备份（把备份复制回箭头右侧原路径即可回滚，脚本不自动回滚）:'
        foreach ($b in $backups) { Out-Line ('  ' + $b) }
    } else { Out-Line '已备份: 无' }
    Out-Line '未处理: 其余'
}

$script:RawArgs = $args

function Main {
    $target = 'auto'
    $mode = 'append'
    $homeArg = ''
    $action = ''
    $i = 0
    while ($i -lt $script:RawArgs.Count) {
        $a = [string]$script:RawArgs[$i]
        if ($a -in '--target', '--mode', '--home' -and ($i + 1) -ge $script:RawArgs.Count) { Die ("缺少 {0} 的值" -f $a) }
        switch -Exact ($a) {
            '--version' { Out-Line ("agent-config {0} (install.ps1)" -f $VERSION); exit 0 }
            '--target' { $i++; $target = [string]$script:RawArgs[$i] }
            '--mode' { $i++; $mode = [string]$script:RawArgs[$i] }
            '--home' { $i++; $homeArg = [string]$script:RawArgs[$i] }
            '--dry-run' { if ($action) { Die '--dry-run/--apply/--verify 只能选一个' }; $action = 'dry-run' }
            '--apply' { if ($action) { Die '--dry-run/--apply/--verify 只能选一个' }; $action = 'apply' }
            '--verify' { if ($action) { Die '--dry-run/--apply/--verify 只能选一个' }; $action = 'verify' }
            default { Die ("未知参数: {0}" -f $a) }
        }
        $i++
    }
    if (@('auto', 'claude', 'codex', 'agents', 'both') -notcontains $target) { Die ("未知 --target: {0}" -f $target) }
    if (@('append', 'replace', 'abort') -notcontains $mode) { Die ("未知 --mode: {0}" -f $mode) }
    if (-not $action) { $action = 'dry-run' }

    $realHome = $env:HOME
    if (-not $realHome) { $realHome = $env:USERPROFILE }
    $homeBase = $realHome
    if ($homeArg) {
        if ($homeArg -eq '~') { $homeBase = $realHome }
        elseif ($homeArg.StartsWith('~/')) { $homeBase = Join-Path $realHome ($homeArg.Substring(2)) }
        else { $homeBase = $homeArg }
    }

    if (-not $homeBase) { Die 'HOME/USERPROFILE 未设置，无法定位宿主目录；请用 --home 指定' }
    $hosts = @(Resolve-Targets $target $homeBase)

    # 第一遍：全部规划；任何规划错误在此停止（未输出、未写入）
    $plans = @()
    foreach ($ctx in $hosts) {
        $rp = Plan-Rules $ctx $mode
        $sps = @()
        foreach ($name in $SKILL_NAMES) { $sps += (Plan-Skill $ctx $name) }
        $plans += @{ Ctx = $ctx; Rules = $rp; Skills = $sps }
    }

    if ($action -eq 'verify') {
        $allOk = $true
        foreach ($p in $plans) {
            if (-not (Verify-Host $p.Ctx)) { $allOk = $false }
        }
        if ($allOk) { Out-Line "`n结论: 全部通过" } else { Out-Line "`n结论: 存在失败项" }
        if ($allOk) { exit 0 } else { exit 1 }
    }

    foreach ($p in $plans) { Show-Plan $p.Ctx $p.Rules $p.Skills }
    if ($action -ne 'apply') {
        Out-Line "`n以上为 dry-run（未写入任何配置文件）。确认后用 --apply 执行。"
        exit 0
    }

    $ts = $env:AGENT_CONFIG_TS
    if (-not $ts) { $ts = (Get-Date -Format 'yyyyMMdd_HHmmss') }
    $written = @()
    $backups = @()
    $skipped = @()
    foreach ($p in $plans) {
        try {
            $r = Apply-Rules $p.Ctx $p.Rules $ts
            if ($r.Status -eq '跳过') {
                $skipped += ("{0} 规则: 已最新" -f $p.Ctx.Key)
            } else {
                $written += ("{0} 规则: {1}" -f $p.Ctx.Key, $r.Status)
            }
            if ($r.Backup) { $backups += ("{0} -> {1}" -f $r.Backup, $p.Rules.Target) }
            foreach ($sp in $p.Skills) {
                $s = Apply-Skill $p.Ctx $sp $ts
                if ($s.Status -eq '跳过') {
                    $skipped += ("{0} Skill {1}: 已最新" -f $p.Ctx.Key, $sp.Name)
                } else {
                    $written += ("{0} Skill {1}: {2}" -f $p.Ctx.Key, $sp.Name, $s.Status)
                }
                if ($s.Backup) { $backups += ("{0} -> {1}" -f $s.Backup, $sp.Target) }
            }
        } catch {
            Fail-Report $_.Exception.Message $written $backups
            exit 1
        }
    }
    Out-Line "`n=== 执行结果 ==="
    foreach ($pair in @(@('写入', $written), @('备份', $backups), @('跳过', $skipped))) {
        if ($pair[1].Count -gt 0) {
            Out-Line ($pair[0] + ':')
            foreach ($w in $pair[1]) { Out-Line ('  ' + $w) }
        }
    }
    Out-Line ("`n下一步: powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 --verify --target {0}" -f $target)
    exit 0
}

Main
